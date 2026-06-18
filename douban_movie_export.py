"""
豆瓣记录导出工具

抓取指定豆瓣用户的电影（已看/想看）和图书（已读/想读）列表，
分别输出 CSV 和 Markdown。

用法:
  python douban_movie_export.py <用户名> [--cookie "cookie字符串"] [--type movie|book|all]

示例:
  python douban_movie_export.py 1234567
  python douban_movie_export.py 1234567 --type book
  python douban_movie_export.py 1234567 --cookie "ll=\"...\"" --type all
"""

import argparse
import csv
import random
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 常量 ──────────────────────────────────────────────────────
URLS = {
    "movie": {
        "collect": "https://movie.douban.com/people/{user}/collect",  # 已看
        "wish":    "https://movie.douban.com/people/{user}/wish",     # 想看
    },
    "book": {
        "collect": "https://book.douban.com/people/{user}/collect",   # 已读
        "wish":    "https://book.douban.com/people/{user}/wish",      # 想读
    },
    "music": {
        "collect": "https://music.douban.com/people/{user}/collect",  # 已听
        "wish":    "https://music.douban.com/people/{user}/wish",     # 想听
    },
}

# 每个类型对应的标签文字
LABELS = {
    "movie": {"collect": "已看", "wish": "想看", "unit": "部"},
    "book":  {"collect": "已读", "wish": "想读", "unit": "本"},
    "music": {"collect": "已听", "wish": "想听", "unit": "张"},
}

# 输出文件名后缀
SUFFIXES = {
    "movie": {"collect": "movies", "wish": "movie_wish"},
    "book":  {"collect": "books",  "wish": "book_wish"},
    "music": {"collect": "music",  "wish": "music_wish"},
}

PAGE_SIZE = 30
DELAY_RANGE = (2, 4)  # 每页间隔秒数

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://movie.douban.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

OUTPUT_DIR = Path(__file__).resolve().parent / "result"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── 抓取 ──────────────────────────────────────────────────────

def fetch_page(session: requests.Session, url: str, start: int) -> str | None:
    """抓取单页，返回 HTML 文本；403/异常返回 None。"""
    params = {
        "start": start,
        "sort": "time",
        "rating": "all",
        "filter": "all",
        "mode": "list",
    }
    try:
        resp = session.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 403:
            print("[!] 403 Forbidden — 可能需要 Cookie 或被临时封禁")
            return None
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"[!] 请求失败: {e}")
        return None


def parse_items(html: str) -> list[dict]:
    """从列表页 HTML 中解析电影条目。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # mode=list 下，每条记录在 <li class="item"> 或 <div class="item">
    for el in soup.select(".item"):
        # 片名
        title_tag = el.select_one(".title a") or el.select_one("a")
        title = title_tag.get_text(strip=True) if title_tag else ""
        link = title_tag["href"].strip(
        ) if title_tag and title_tag.has_attr("href") else ""

        # 评分: class 形如 "rating5-t" → 5 星
        rating = ""
        rating_tag = el.select_one(
            ".date span[class*='rating']") or el.select_one("span[class*='rating']")
        if rating_tag:
            cls = " ".join(rating_tag.get("class", []))
            m = re.search(r"rating(\d)", cls)
            if m:
                rating = m.group(1)

        # 标记日期
        date = ""
        date_tag = el.select_one(".date")
        if date_tag:
            raw = date_tag.get_text(strip=True)
            # 提取 "2024-03-15" 格式
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
            date = m.group(1) if m else raw

        # 导演/主演/年份简介
        info = ""
        intro_tag = el.select_one(".intro")
        if intro_tag:
            info = intro_tag.get_text(strip=True)

        # 短评/备注
        comment = ""
        comment_tag = el.select_one(".comment")
        if comment_tag:
            comment = comment_tag.get_text(strip=True)

        # 海报图 URL
        poster = ""
        img_tag = el.select_one("img")
        if img_tag:
            poster = img_tag.get("src", "")

        if title:
            items.append({
                "title": title,
                "rating": rating,
                "date": date,
                "link": link,
                "info": info,
                "comment": comment,
                "poster": poster,
            })

    return items


def scrape_all(session: requests.Session, url: str, label: str, unit: str = "部") -> list[dict]:
    """逐页抓取，按 link 去重。"""
    all_items: list[dict] = []
    seen_links: set[str] = set()
    start = 0
    page = 1

    while True:
        print(f"  [{label} 第 {page} 页] start={start} ...", end=" ", flush=True)
        html = fetch_page(session, url, start)
        if html is None:
            print("停止")
            break

        items = parse_items(html)
        if not items:
            print("无更多数据")
            break

        # 去重
        new_items = []
        for item in items:
            key = item["link"] or (item["title"], item["date"])
            if key not in seen_links:
                seen_links.add(key)
                new_items.append(item)
        print(f"获取 {len(items)} {unit} (新增 {len(new_items)})")
        all_items.extend(new_items)

        # 页返回量不足 PAGE_SIZE 时仍可能有下一页，用宽松阈值判断
        if len(items) < PAGE_SIZE - 5:
            break

        start += PAGE_SIZE
        page += 1
        time.sleep(random.uniform(*DELAY_RANGE))

    return all_items


# ── 导出 ──────────────────────────────────────────────────────

def export_csv(items: list[dict], filepath: Path, name_col: str = "片名"):
    """导出 CSV（UTF-8 BOM，Excel 友好）。"""
    fieldnames = ["title", "rating", "date",
                  "info", "comment", "poster", "link"]
    header_map = {
        "title": name_col, "rating": "评分", "date": "日期",
        "info": "简介", "comment": "短评", "poster": "封面", "link": "链接",
    }

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        # 写中文表头
        writer.writerow(header_map)
        writer.writerows(items)

    print(f"  CSV → {filepath.name}  ({len(items)} 条)")


def export_markdown(items: list[dict], filepath: Path, title: str = "列表",
                    name_col: str = "片名"):
    """导出 Markdown 表格。"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"共 {len(items)} 条\n\n")
        f.write(f"| {name_col} | 评分 | 日期 | 简介 | 短评 | 封面 | 链接 |\n")
        f.write(f"|{'----|' * 7}\n")
        for item in items:
            stars = f"{'⭐' * int(item['rating'])}" if item["rating"] else ""
            title = item["title"].replace("|", "\\|")
            info = item["info"].replace("|", "\\|")
            comment = item["comment"].replace("|", "\\|")
            poster = f"![]({item['poster']})" if item["poster"] else ""
            link = f"[豆瓣]({item['link']})" if item["link"] else ""
            f.write(
                f"| {title} | {stars} | {item['date']} | {info} | {comment} | {poster} | {link} |\n")

    print(f"  MD  → {filepath.name}")


# ── 入口 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="豆瓣记录导出工具（电影 + 图书 + 音乐）")
    parser.add_argument("user", help="豆瓣用户 ID（URL 中 /people/ 后面的部分）")
    parser.add_argument("--cookie", default="",
                        help="浏览器 Cookie 字符串（可选，绕过访问限制）")
    parser.add_argument("--type", default="all", choices=["movie", "book", "music", "all"],
                        help="导出类型: movie=仅电影, book=仅图书, music=仅音乐, all=全部 (默认 all)")
    args = parser.parse_args()

    session = requests.Session()
    if args.cookie:
        session.headers["Cookie"] = args.cookie

    # 确定要抓取的类型
    types = ["movie", "book", "music"] if args.type == "all" else [args.type]

    # 类型 → 中文列名/标签映射
    NAME_COLS = {"movie": "片名", "book": "书名", "music": "专辑名"}
    TYPE_LABELS = {"movie": "电影", "book": "图书", "music": "音乐"}

    for dtype in types:
        name_col = NAME_COLS[dtype]
        type_label = TYPE_LABELS[dtype]
        unit = LABELS[dtype]["unit"]

        for category in ["collect", "wish"]:
            label = LABELS[dtype][category]
            suffix = SUFFIXES[dtype][category]
            url = URLS[dtype][category].format(user=args.user)

            print(f"\n{'='*50}")
            print(f"[*] 抓取用户 {args.user} 的「{label}」{type_label}...")
            print(f"{'='*50}\n")
            items = scrape_all(session, url, label, unit=unit)

            if not items:
                print(f"  [!] 「{label}」无数据，跳过。")
                continue

            print(
                f"\n  共获取 {len(items)} {unit}「{label}」{type_label}，正在导出...\n")
            export_csv(items, OUTPUT_DIR /
                       f"{args.user}_{suffix}.csv", name_col=name_col)
            export_markdown(
                items,
                OUTPUT_DIR / f"{args.user}_{suffix}.md",
                title=f"{label}{type_label}列表",
                name_col=name_col,
            )

    print("\n[完成] 全部导出成功！")


if __name__ == "__main__":
    main()
