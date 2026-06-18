"""
豆瓣数据爬取模块（并发 + 增量缓存优化版）

优化项：
1. 并发爬取：ThreadPoolExecutor 同时爬取不同子站（movie/book/music）
2. 智能延迟：有 Cookie 时缩短请求间隔（1-2s），无 Cookie 保持保守间隔（2-4s）
3. 增量缓存：对比已有 CSV 缓存，只爬取新增数据，未变化的条目直接复用

从 douban_movie_export.py 提取核心爬取逻辑，增加进度回调，
供 Web 应用异步调用。
"""

import csv
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

from . import config

# ── URL 模板 ──────────────────────────────────────────────
URLS = {
    "movie": {
        "collect": "https://movie.douban.com/people/{user}/collect",
        "wish":    "https://movie.douban.com/people/{user}/wish",
    },
    "book": {
        "collect": "https://book.douban.com/people/{user}/collect",
        "wish":    "https://book.douban.com/people/{user}/wish",
    },
    "music": {
        "collect": "https://music.douban.com/people/{user}/collect",
        "wish":    "https://music.douban.com/people/{user}/wish",
    },
}

LABELS = {
    "movie": {"collect": "已看", "wish": "想看", "unit": "部"},
    "book":  {"collect": "已读", "wish": "想读", "unit": "本"},
    "music": {"collect": "已听", "wish": "想听", "unit": "张"},
}

SUFFIXES = {
    "movie": {"collect": "movies", "wish": "movie_wish"},
    "book":  {"collect": "books",  "wish": "book_wish"},
    "music": {"collect": "music",  "wish": "music_wish"},
}

NAME_COLS = {"movie": "片名", "book": "书名", "music": "专辑名"}


# ── 进度回调类型 ──────────────────────────────────────────
# progress_callback(phase: str, percent: int, message: str)
ProgressCallback = Optional[Callable[[str, int, str], None]]


# ── 用户 ID 解析 ──────────────────────────────────────────

def parse_user_id(input_str: str) -> str:
    """从用户输入中提取豆瓣 user_id。

    支持格式：
    - 纯 ID: "1234567"
    - URL: "https://movie.douban.com/people/1234567/"
    - URL: "https://www.douban.com/people/feizhaizhangmen/"
    """
    input_str = input_str.strip()

    # 已经是纯 ID（无 / 和 :）
    if "/" not in input_str and ":" not in input_str:
        return input_str

    # 从 URL 中提取
    m = re.search(r"douban\.com/people/([^/?#]+)", input_str)
    if m:
        return m.group(1)

    # 兜底：取最后一段路径
    m = re.search(r"/([^/?#]+)/?$", input_str)
    if m:
        return m.group(1)

    return input_str


# ── HTTP 请求 ──────────────────────────────────────────────

def _make_session(cookie: str = "") -> requests.Session:
    """创建带 UA 和可选 Cookie 的 Session。"""
    s = requests.Session()
    s.headers.update(config.DOUBAN_HEADERS)
    if cookie:
        s.headers["Cookie"] = cookie
    return s


def _fetch_page(session: requests.Session, url: str, start: int) -> tuple[Optional[str], Optional[str]]:
    """抓取单页 HTML，返回 (html, error_kind)。"""
    params = {
        "start": start,
        "sort": "time",
        "rating": "all",
        "filter": "all",
        "mode": "list",
    }
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 403:
            return None, "forbidden"
        resp.raise_for_status()
        return resp.text, None
    except requests.Timeout:
        return None, "timeout"
    except requests.RequestException:
        return None, "network_error"


# ── HTML 解析 ──────────────────────────────────────────────

def _parse_items(html: str) -> list[dict]:
    """从列表页 HTML 解析条目。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for el in soup.select(".item"):
        title_tag = el.select_one(".title a") or el.select_one("a")
        title = title_tag.get_text(strip=True) if title_tag else ""
        link = (title_tag["href"].strip()
                if title_tag and title_tag.has_attr("href") else "")

        # 评分
        rating = ""
        rating_tag = (el.select_one(".date span[class*='rating']")
                      or el.select_one("span[class*='rating']"))
        if rating_tag:
            cls = " ".join(rating_tag.get("class", []))
            m = re.search(r"rating(\d)", cls)
            if m:
                rating = m.group(1)

        # 日期
        date = ""
        date_tag = el.select_one(".date")
        if date_tag:
            raw = date_tag.get_text(strip=True)
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            date = m.group(1) if m else raw

        # 简介
        info = ""
        intro_tag = el.select_one(".intro")
        if intro_tag:
            info = intro_tag.get_text(strip=True)

        # 短评
        comment = ""
        comment_tag = el.select_one(".comment")
        if comment_tag:
            comment = comment_tag.get_text(strip=True)

        # 海报
        poster = ""
        img_tag = el.select_one("img")
        if img_tag:
            poster = img_tag.get("src", "")

        if title:
            items.append({
                "title": title, "rating": rating, "date": date,
                "link": link, "info": info, "comment": comment,
                "poster": poster,
            })

    return items


# ── 智能延迟 ──────────────────────────────────────────────

def _page_delay(has_cookie: bool):
    """根据是否有 Cookie 返回随机延迟秒数。

    有 Cookie（已登录）：1-2s，请求可以更激进
    无 Cookie（匿名）：2-4s，保守避免 403
    """
    if has_cookie:
        return random.uniform(
            config.SCRAPE_DELAY_MIN_COOKIE,
            config.SCRAPE_DELAY_MAX_COOKIE,
        )
    return random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX)


# ── 增量缓存 ──────────────────────────────────────────────

def _load_cached_items(csv_path: Path) -> list[dict]:
    """从已有 CSV 加载缓存条目，用于增量对比。"""
    if not csv_path.exists():
        return []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def _item_key(item: dict) -> tuple:
    """生成条目去重键。"""
    return (item.get("link", ""), item.get("title", ""), item.get("date", ""))


def _is_cache_fresh(
    session: requests.Session,
    url: str,
    cached_items: list[dict],
) -> bool:
    """检查缓存是否仍然新鲜：抓取第一页，若所有条目都已在缓存中则跳过全量爬取。"""
    if not cached_items:
        return False

    cached_keys = {_item_key(it) for it in cached_items}

    html, _ = _fetch_page(session, url, 0)
    if html is None:
        # 请求失败，保守起见视为过期
        return False

    first_page = _parse_items(html)
    if not first_page:
        return False

    # 第一页全部命中缓存 → 无新增数据
    new_count = sum(1 for it in first_page if _item_key(it) not in cached_keys)
    return new_count == 0


# ── 逐页爬取 ─────────────────────────────────────────

def _scrape_all(
    session: requests.Session,
    url: str,
    label: str,
    unit: str,
    phase: str,
    progress: ProgressCallback,
    base_percent: int,
    percent_span: int,
    has_cookie: bool = False,
) -> tuple[list[dict], dict | None]:
    """逐页抓取并去重。"""
    all_items: list[dict] = []
    seen_keys: set[tuple] = set()
    start = 0
    page = 1
    failure: dict | None = None

    while True:
        if progress:
            pct = base_percent + min(
                int(percent_span * (page - 1) / max(page, 1)),
                percent_span - 1,
            )
            progress(phase, pct, f"正在爬取{label}第 {page} 页...")

        html, error_kind = _fetch_page(session, url, start)
        if html is None:
            failure = {
                "kind": error_kind or "unknown",
                "page": page,
                "start": start,
                "url": url,
                "message": f"{label}第 {page} 页抓取失败",
            }
            if progress:
                progress(
                    phase, base_percent + percent_span,
                    f"{label}：{failure['kind']}，停止爬取",
                )
            break

        items = _parse_items(html)
        if not items:
            break

        for item in items:
            key = _item_key(item)
            if key not in seen_keys:
                seen_keys.add(key)
                all_items.append(item)

        if progress:
            progress(
                phase, base_percent + percent_span,
                f"{label}：累计 {len(all_items)} {unit}",
            )

        # 页不满 → 已到最后一页
        if len(items) < config.PAGE_SIZE - 5:
            break

        start += config.PAGE_SIZE
        page += 1
        time.sleep(_page_delay(has_cookie))

    return all_items, failure


# ── CSV 导出 ──────────────────────────────────────────────

def _export_csv(items: list[dict], filepath: Path, name_col: str):
    """导出 CSV（UTF-8 BOM）。"""
    fieldnames = ["title", "rating", "date",
                  "info", "comment", "poster", "link"]
    header_map = {
        "title": name_col, "rating": "评分", "date": "日期",
        "info": "简介", "comment": "短评", "poster": "封面", "link": "链接",
    }
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(header_map)
        writer.writerows(items)


# ── 单个爬取任务 ──────────────────────────────────────────

def _scrape_task(
    user_id: str,
    dtype: str,
    category: str,
    cookie: str,
    data_dir: Path,
    progress: ProgressCallback,
    base_pct: int,
    step_pct: int,
) -> tuple[str, str, list[dict]]:
    """单个爬取任务：创建独立 Session，优先复用缓存，否则从头爬取。

    返回 (dtype, category, items, failure) 元组。
    """
    label = LABELS[dtype][category]
    url = URLS[dtype][category].format(user=user_id)
    phase = f"scraping_{dtype}"

    session = _make_session(cookie)
    has_cookie = bool(cookie)

    if progress:
        progress(phase, base_pct, f"开始爬取「{label}」...")

    # 增量缓存：检查已有 CSV 是否仍然新鲜
    suffix = SUFFIXES[dtype][category]
    csv_path = data_dir / f"{user_id}_{suffix}.csv"
    cached = _load_cached_items(csv_path)
    if cached and _is_cache_fresh(session, url, cached):
        if progress:
            progress(
                phase, base_pct + step_pct,
                f"{label}：缓存命中（{len(cached)} {LABELS[dtype]['unit']}），跳过爬取",
            )
        return dtype, category, cached, None

    items, failure = _scrape_all(
        session, url, label, LABELS[dtype]["unit"],
        phase=phase,
        progress=progress,
        base_percent=base_pct,
        percent_span=step_pct,
        has_cookie=has_cookie,
    )

    return dtype, category, items, failure


# ── 主入口（并发版） ──────────────────────────────────────

def scrape_user(
    user_id: str,
    cookie: str = "",
    types: list[str] | None = None,
    progress: ProgressCallback = None,
) -> dict:
    """爬取指定用户的全部数据，使用线程池并发加速。

    优化策略：
    - 不同子站（movie/book/music）同时爬取，各自独立 Session
    - 有 Cookie 时请求间隔从 2-4s 降至 1-2s

    参数:
        user_id: 豆瓣用户 ID
        cookie: 可选的 Cookie 字符串
        types: 要爬取的类型列表，默认 ["movie", "book", "music"]
        progress: 进度回调 (phase, percent, message)

    返回:
        {"movie": {"collect": [...], "wish": [...]}, "book": {...}, ...}
    """
    if types is None:
        types = ["movie", "book", "music"]

    data_dir = config.DATA_DIR / user_id
    data_dir.mkdir(parents=True, exist_ok=True)

    # 初始化结果结构
    result = {dtype: {"collect": [], "wish": []} for dtype in types}
    meta = {
        "errors": [],
        "types": types,
        "cookie_provided": bool(cookie),
        "total_tasks": len(types) * 2,
    }

    # 计算进度分配
    total_steps = len(types) * 2  # 每个类型有 collect + wish
    step_percent = 80 // total_steps

    # 构建任务列表
    tasks = []
    step = 0
    for dtype in types:
        for category in ["collect", "wish"]:
            base_pct = step * step_percent
            tasks.append((dtype, category, base_pct, step_percent))
            step += 1

    if progress:
        progress(
            "scraping_start", 0,
            f"并发爬取启动（{len(tasks)} 个任务，"
            f"{'Cookie 加速模式' if cookie else '匿名模式'}）",
        )

    # 并发执行：不同子站同时爬取
    with ThreadPoolExecutor(max_workers=config.CONCURRENT_SCRAPERS) as pool:
        futures = {
            pool.submit(
                _scrape_task,
                user_id, dtype, category, cookie, data_dir,
                progress, base_pct, step_pct,
            ): (dtype, category)
            for dtype, category, base_pct, step_pct in tasks
        }

        for future in as_completed(futures):
            try:
                dtype, category, items, failure = future.result()
                result[dtype][category] = items

                # 导出 CSV
                if items:
                    suffix = SUFFIXES[dtype][category]
                    csv_path = data_dir / f"{user_id}_{suffix}.csv"
                    _export_csv(items, csv_path, NAME_COLS[dtype])
                if failure:
                    meta["errors"].append({
                        "dtype": dtype,
                        "category": category,
                        **failure,
                    })
            except Exception as e:
                dtype, category = futures[future]
                if progress:
                    progress(
                        f"scraping_{dtype}", 0,
                        f"{LABELS[dtype][category]}爬取失败: {e}",
                    )
                meta["errors"].append({
                    "dtype": dtype,
                    "category": category,
                    "kind": "exception",
                    "message": str(e),
                })

    if progress:
        # 统计总数
        total = sum(
            len(result[dt][cat])
            for dt in result
            for cat in result[dt]
        )
        progress("scraping_done", 80, f"爬取完成，共 {total} 条数据")

    meta["total_items"] = sum(
        len(result[dt][cat])
        for dt in result
        for cat in result[dt]
    )
    meta["has_errors"] = bool(meta["errors"])
    result["_meta"] = meta

    return result
