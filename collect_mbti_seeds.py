"""
MBTI 种子用户采集脚本 v2

策略：
- 从 MBTI 相关小组的讨论帖中提取自报类型的用户
- 帖子标题含 MBTI 类型关键词时，优先检查楼主正文和回帖中的自报
- 必要时回访用户主页 bio 做二次验证

用法：
    python collect_mbti_seeds.py --cookie "你的 cookie" --max-seeds 500

输出：
    data/mbti_training/seeds.json
    data/mbti_training/seed_failures.json
    data/mbti_training/seed_progress.json
"""

import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MBTI_TYPES = [
    "INFJ", "INFP", "INTJ", "INTP",
    "ISFJ", "ISFP", "ISTJ", "ISTP",
    "ENFJ", "ENFP", "ENTJ", "ENTP",
    "ESFJ", "ESFP", "ESTJ", "ESTP",
]

MBTI_PATTERN = re.compile(r"\b([IE][NS][FT][JP])\b", re.IGNORECASE)
SELF_REPORT_PATTERNS = [
    re.compile(r"我(?:是|测出|测的|的(?:结果|类型)?(?:是)?|属于)\s*([IE][NS][FT][JP])", re.IGNORECASE),
    re.compile(r"(?:作为|身为|典型的?)\s*([IE][NS][FT][JP])", re.IGNORECASE),
    re.compile(r"([IE][NS][FT][JP])\s*(?:本人|一枚|一个|路过)", re.IGNORECASE),
]

TARGET_GROUPS = [
    ("14782", "INFJ/人格"),
    ("25519", "INFP"),
    ("42898", "INTP"),
    ("51369", "INTJ"),
    ("103117", "ENFP"),
    ("100795", "ENFJ"),
    ("35439", "ENTJ"),
    ("75085", "ENTP"),
    ("46388", "ISFJ"),
    ("76117", "ISFP"),
    ("38871", "ISTJ"),
    ("64551", "ISTP"),
    ("62099", "ESFJ"),
    ("75363", "ESFP"),
    ("62736", "ESTJ"),
    ("66821", "ESTP"),
]

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "data" / "mbti_training"
SEED_PATH = OUTPUT_DIR / "seeds.json"
FAILURE_PATH = OUTPUT_DIR / "seed_failures.json"
PROGRESS_PATH = OUTPUT_DIR / "seed_progress.json"
DOTENV_PATH = ROOT / ".env"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class RateLimitExceeded(RuntimeError):
    """豆瓣返回 429，当前批次应尽快停止。"""


class LoginGateBlocked(RuntimeError):
    """命中豆瓣登录跳转页，当前批次应立即停止。"""


def safe_print(text: str):
    """在 Windows 控制台中尽量稳定输出。"""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def load_existing_seed_map() -> dict[str, dict]:
    if not SEED_PATH.exists():
        return {}

    try:
        payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, list):
        return {}

    seeds: dict[str, dict] = {}
    for item in payload:
        user_id = item.get("user_id")
        if user_id:
            seeds[user_id] = item
    return seeds


def save_progress(seeds: dict[str, dict], failures: list[dict], meta: dict | None = None) -> int:
    """增量保存采集结果，并保留历史已采到的种子。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    merged_seeds = load_existing_seed_map()
    merged_seeds.update({user_id: row for user_id, row in seeds.items() if user_id})

    with open(SEED_PATH, "w", encoding="utf-8") as f:
        json.dump(list(merged_seeds.values()), f, ensure_ascii=False, indent=2)

    with open(FAILURE_PATH, "w", encoding="utf-8") as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)

    if meta is not None:
        enriched_meta = dict(meta)
        enriched_meta["seed_count"] = len(seeds)
        enriched_meta["stored_seed_count"] = len(merged_seeds)
        enriched_meta["failure_count"] = len(failures)
        with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
            json.dump(enriched_meta, f, ensure_ascii=False, indent=2)

    return len(merged_seeds)


def resolve_cookie(cli_cookie: str = "") -> str:
    """按 CLI > 环境变量 > .env 顺序读取 Cookie。"""
    if cli_cookie:
        return cli_cookie

    env_cookie = os.environ.get("DOUBAN_COOKIE", "").strip()
    if env_cookie:
        return env_cookie

    if not DOTENV_PATH.exists():
        return ""

    for line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "DOUBAN_COOKIE":
            return value.strip().strip('"').strip("'")

    return ""


def make_session(cookie: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def append_failure(failures: list[dict] | None, stage: str, reason: str, **payload):
    if failures is None:
        return
    failures.append({"stage": stage, "reason": reason, **payload})


def _is_login_gate_response(resp: requests.Response | None) -> bool:
    if resp is None:
        return False

    if getattr(resp, "url", "").startswith("https://sec.douban.com/b"):
        return True

    text = getattr(resp, "text", "") or ""
    return "有异常请求从你的 IP 发出" in text or "登录跳转页" in text


def follow_sec_redirect(session: requests.Session, resp: requests.Response) -> requests.Response | None:
    """跟进 sec.douban.com 跳转，但不在这里落失败记录。"""
    if resp.status_code not in (301, 302, 303, 307, 308):
        return None

    location = resp.headers.get("Location", "")
    if not location:
        return None

    redirect_url = urljoin(resp.url, location)
    parsed = urlparse(redirect_url)
    return session.get(redirect_url, timeout=20, allow_redirects=True) if parsed.netloc else None


def _solve_pow(challenge: str, difficulty: int = 4) -> int:
    prefix = "0" * difficulty
    nonce = 0
    while True:
        nonce += 1
        digest = hashlib.sha512((challenge + str(nonce)).encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            return nonce


def maybe_solve_sec_challenge(
    session: requests.Session,
    resp: requests.Response,
    failures: list[dict] | None = None,
    context: dict | None = None,
) -> requests.Response | None:
    """如果命中可解 sec challenge，则自动求解并重放请求。"""
    if _is_login_gate_response(resp):
        return None

    if "请点击下方按钮继续浏览" not in resp.text:
        return None

    html = resp.text
    tok_match = re.search(r'name="tok" value="([^"]+)"', html)
    cha_match = re.search(r'name="cha" value="([^"]+)"', html)
    red_match = re.search(r'name="red" value="([^"]+)"', html)
    action_match = re.search(r'<form[^>]+action="([^"]+)"', html)
    if not (tok_match and cha_match and red_match and action_match):
        append_failure(
            failures,
            "sec_challenge",
            "挑战页字段不完整，无法自动求解",
            url=resp.url,
            **(context or {}),
        )
        return None

    try:
        nonce = _solve_pow(cha_match.group(1))
        submit_url = urljoin(resp.url, action_match.group(1))
        return session.post(
            submit_url,
            data={
                "tok": tok_match.group(1),
                "cha": cha_match.group(1),
                "sol": str(nonce),
                "red": red_match.group(1),
            },
            headers={
                "Referer": resp.url,
                "Origin": "https://sec.douban.com",
            },
            timeout=20,
            allow_redirects=True,
        )
    except Exception as exc:
        append_failure(
            failures,
            "sec_challenge",
            f"挑战求解失败: {exc}",
            url=resp.url,
            **(context or {}),
        )
        return None


def safe_get(
    session: requests.Session,
    url: str,
    failures: list[dict] | None = None,
    context: dict | None = None,
    delay: tuple[float, float] = (0, 0),
) -> requests.Response | None:
    # 自动延迟：有 Cookie 时更激进
    if delay == (0, 0):
        has_cookie = bool(session.headers.get("Cookie", ""))
        delay = (1, 2.5) if has_cookie else (2, 4)
    time.sleep(random.uniform(*delay))

    try:
        resp = session.get(url, timeout=15, allow_redirects=False)
        redirect_resp = follow_sec_redirect(session, resp)
        if redirect_resp is not None:
            resp = redirect_resp

        challenge_resp = maybe_solve_sec_challenge(
            session,
            resp,
            failures=failures,
            context=context,
        )
        if challenge_resp is not None:
            resp = challenge_resp

        if _is_login_gate_response(resp):
            append_failure(
                failures,
                "sec_gate",
                "命中登录跳转页，当前会话需要登录态或 Cookie",
                url=resp.url,
                **(context or {}),
            )
            safe_print(f"  [GATE] {url}")
            raise LoginGateBlocked(url)

        if resp.status_code == 429:
            append_failure(
                failures,
                "http_get",
                "429 Too Many Requests",
                url=url,
                **(context or {}),
            )
            raise RateLimitExceeded(url)

        if resp.status_code == 403:
            append_failure(
                failures,
                "http_get",
                "403 Forbidden",
                url=url,
                **(context or {}),
            )
            safe_print(f"  [403] {url}")
            return None

        resp.raise_for_status()
        return resp
    except (RateLimitExceeded, LoginGateBlocked):
        raise
    except Exception as exc:
        append_failure(
            failures,
            "http_get",
            str(exc),
            url=url,
            **(context or {}),
        )
        safe_print(f"  [ERR] {url}: {exc}")
        return None


def get_discussion_topics(
    session: requests.Session,
    group_id: str,
    failures: list[dict],
    max_pages: int = 5,
) -> list[dict]:
    topics = []
    seen_urls = set()

    for page in range(max_pages):
        start = page * 25
        url = f"https://www.douban.com/group/{group_id}/discussion?start={start}&type=new"
        safe_print(f"  讨论列表页 {page + 1}: start={start}")

        resp = safe_get(
            session,
            url,
            failures=failures,
            context={"group_id": group_id, "page": page + 1, "kind": "discussion_list"},
        )
        if resp is None:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.olt") or soup.select_one("table")
        if not table:
            append_failure(
                failures,
                "parse_discussion_list",
                "未找到讨论表格",
                url=url,
                group_id=group_id,
                page=page + 1,
            )
            safe_print("  [WARN] 未找到讨论表格")
            break

        rows = table.select("tr")[1:]
        found_new = False
        for row in rows:
            title_link = row.select_one("td.title a") or row.select_one("a[href*='topic']")
            if not title_link:
                continue

            topic_url = title_link.get("href", "").split("?")[0]
            if not topic_url or topic_url in seen_urls:
                continue

            title = title_link.get_text(strip=True)
            seen_urls.add(topic_url)
            found_new = True

            author_uid = None
            links = row.select("a")
            author_link = row.select_one("td:nth-child(2) a") or (links[1] if len(links) > 1 else None)
            if author_link:
                match = re.search(r"douban\.com/people/([^/?#]+)", author_link.get("href", ""))
                if match:
                    author_uid = match.group(1)

            reply_count = 0
            reply_cell = row.select_one("td.r-count") or (row.select("td")[2] if len(row.select("td")) > 2 else None)
            if reply_cell:
                try:
                    reply_count = int(reply_cell.get_text(strip=True) or 0)
                except ValueError:
                    reply_count = 0

            topics.append(
                {
                    "title": title,
                    "url": topic_url,
                    "author_uid": author_uid,
                    "reply_count": reply_count,
                }
            )

        if not found_new:
            break

    return topics


def filter_mbti_topics(topics: list[dict]) -> list[dict]:
    filtered = []
    seen = set()

    for topic in topics:
        title_lower = topic["title"].lower()
        match_hint = None
        for mbti in MBTI_TYPES:
            if mbti.lower() in title_lower:
                match_hint = mbti
                break

        has_generic_kw = any(keyword in title_lower for keyword in ["mbti", "人格", "类型", "十六型", "性格类型"])
        if not (match_hint or has_generic_kw):
            continue

        if topic["url"] in seen:
            continue

        seen.add(topic["url"])
        row = dict(topic)
        if match_hint:
            row["mbti_hint"] = match_hint
        filtered.append(row)

    return filtered


def scrape_topic_replies(
    session: requests.Session,
    topic_url: str,
    failures: list[dict],
    max_pages: int = 3,
) -> list[dict]:
    replies = []

    for page in range(max_pages):
        start = page * 100
        url = f"{topic_url}?start={start}" if page > 0 else topic_url
        resp = safe_get(
            session,
            url,
            failures=failures,
            context={"topic_url": topic_url, "page": page + 1, "kind": "topic_replies"},
            delay=(2, 5),
        )
        if resp is None:
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        if page == 0:
            author_link = soup.select_one(".topic-doc .from a") or soup.select_one("[class*='author'] a")
            if author_link:
                match = re.search(r"douban\.com/people/([^/?#]+)", author_link.get("href", ""))
                if match:
                    content = soup.select_one("#link-report")
                    replies.append(
                        {
                            "uid": match.group(1),
                            "text": content.get_text(" ", strip=True)[:500] if content else "",
                            "is_author": True,
                        }
                    )

        for reply in soup.select(".reply-doc"):
            author_link = reply.select_one(".from a") or reply.select_one("a[href*='people']")
            if not author_link:
                continue

            match = re.search(r"douban\.com/people/([^/?#]+)", author_link.get("href", ""))
            if not match:
                continue

            content = reply.select_one("p") or reply.select_one(".reply-content")
            replies.append(
                {
                    "uid": match.group(1),
                    "text": content.get_text(" ", strip=True)[:500] if content else "",
                    "is_author": False,
                }
            )

    return replies


def extract_self_reported_mbti(text: str) -> str | None:
    for pattern in SELF_REPORT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


def verify_bio_mbti(session: requests.Session, uid: str, failures: list[dict]) -> str | None:
    url = f"https://www.douban.com/people/{uid}/"
    resp = safe_get(
        session,
        url,
        failures=failures,
        context={"user_id": uid, "kind": "bio_verify"},
        delay=(1, 3),
    )
    if resp is None:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    direct = extract_self_reported_mbti(full_text)
    if direct:
        return direct

    bio_div = soup.select_one("#display .intro") or soup.select_one(".user-intro")
    if not bio_div:
        return None

    loose = MBTI_PATTERN.search(bio_div.get_text(" ", strip=True))
    return loose.group(1).upper() if loose else None


def collect_all_seeds(
    cookie: str = "",
    max_seeds: int = 500,
    max_groups: int = 0,
    topic_limit: int = 20,
    discussion_pages: int = 5,
    reply_pages: int = 2,
) -> tuple[list[dict], list[dict]]:
    session = make_session(cookie)
    seeds: dict[str, dict] = {}
    failures: list[dict] = []
    bio_cache: dict[str, str | None] = {}

    # 加载已有种子，避免重复采集
    existing_seed_map = load_existing_seed_map()
    existing_seed_count = len(existing_seed_map)
    skipped_existing = 0

    meta = {
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cookie_provided": bool(cookie),
        "mode": "cookie" if cookie else "anonymous",
        "existing_seed_count": existing_seed_count,
        "max_seeds": max_seeds,
        "max_groups": max_groups,
        "topic_limit": topic_limit,
        "discussion_pages": discussion_pages,
        "reply_pages": reply_pages,
        "processed_groups": [],
    }
    if not cookie:
        meta["note"] = "无 Cookie 时仅做门禁探测；命中登录跳转页后立即停止。"

    groups = TARGET_GROUPS[:max_groups] if max_groups > 0 else TARGET_GROUPS
    total_target = max_seeds  # 目标是累计达到 max_seeds

    for group_id, group_name in groups:
        if len(seeds) + existing_seed_count >= total_target:
            break

        safe_print(f"\n{'=' * 50}")
        safe_print(f"[Group] {group_name} ({group_id})")

        try:
            topics = get_discussion_topics(
                session,
                group_id,
                failures,
                max_pages=discussion_pages,
            )
            safe_print(f"  共 {len(topics)} 个帖子")

            mbti_topics = filter_mbti_topics(topics)
            safe_print(f"  MBTI 相关帖子: {len(mbti_topics)} 个")

            for topic in mbti_topics[:topic_limit]:
                if len(seeds) + existing_seed_count >= total_target:
                    break

                safe_print(f"\n  [Topic] {topic['title'][:40]}...")
                replies = scrape_topic_replies(
                    session,
                    topic["url"],
                    failures,
                    max_pages=reply_pages,
                )

                for reply in replies:
                    uid = reply["uid"]
                    if uid in seeds:
                        continue

                    # 跳过已有种子
                    if uid in existing_seed_map:
                        skipped_existing += 1
                        continue

                    mbti = extract_self_reported_mbti(reply["text"])
                    source = "post_reply"

                    if not mbti and reply.get("is_author") and topic.get("mbti_hint"):
                        mbti = topic["mbti_hint"]
                        source = "topic_author"

                    if not mbti:
                        if uid not in bio_cache:
                            bio_cache[uid] = verify_bio_mbti(session, uid, failures)
                        bio_mbti = bio_cache[uid]
                        if bio_mbti:
                            mbti = bio_mbti
                            source = "bio"

                    if not mbti:
                        append_failure(
                            failures,
                            "extract_mbti",
                            "未从帖子或 bio 中提取到 MBTI",
                            user_id=uid,
                            topic_url=topic["url"],
                        )
                        save_progress(seeds, failures, meta)
                        continue

                    seeds[uid] = {
                        "user_id": uid,
                        "mbti": mbti,
                        "source": source,
                        "confidence": "self_reported",
                        "discovered_at": datetime.now().strftime("%Y-%m-%d"),
                    }
                    safe_print(f"    [OK] {uid} -> {mbti} ({source})")
                    save_progress(seeds, failures, meta)

            meta["processed_groups"].append(
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "topics_found": len(topics),
                    "mbti_topics_found": len(mbti_topics),
                    "seeds_so_far": len(seeds),
                    "failures_so_far": len(failures),
                    "skipped_existing": skipped_existing,
                }
            )
            save_progress(seeds, failures, meta)
        except LoginGateBlocked:
            meta["stopped_reason"] = "login_gate"
            meta["stopped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_progress(seeds, failures, meta)
            safe_print("  [STOP] 命中登录跳转页，当前未提供 Cookie，已停止本批次。")
            break
        except RateLimitExceeded:
            meta["stopped_reason"] = "rate_limit"
            meta["stopped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_progress(seeds, failures, meta)
            safe_print("  [STOP] 命中 429，已提前结束本批次并落盘。")
            break

    return list(seeds.values()), failures


def main():
    parser = argparse.ArgumentParser(description="MBTI 种子用户采集 v2")
    parser.add_argument("--cookie", default="", help="豆瓣 Cookie")
    parser.add_argument("--max-seeds", type=int, default=500, help="最大种子数")
    parser.add_argument("--max-groups", type=int, default=0, help="最多处理多少个小组（0=全部）")
    parser.add_argument("--topic-limit", type=int, default=20, help="每个小组最多处理多少个帖子")
    parser.add_argument("--discussion-pages", type=int, default=5, help="每个小组抓多少页讨论列表")
    parser.add_argument("--reply-pages", type=int, default=2, help="每个帖子抓多少页回复")
    args = parser.parse_args()

    cookie = resolve_cookie(args.cookie)
    seeds, failures = collect_all_seeds(
        cookie=cookie,
        max_seeds=args.max_seeds,
        max_groups=args.max_groups,
        topic_limit=args.topic_limit,
        discussion_pages=args.discussion_pages,
        reply_pages=args.reply_pages,
    )

    stored_seed_count = save_progress(
        {item["user_id"]: item for item in seeds},
        failures,
        {
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "seed_count": len(seeds),
            "failure_count": len(failures),
        },
    )

    mbti_counts: dict[str, int] = {}
    for row in seeds:
        mbti_counts[row["mbti"]] = mbti_counts.get(row["mbti"], 0) + 1

    safe_print(f"\n{'=' * 50}")
    safe_print(f"本次新增种子: {len(seeds)}")
    safe_print(f"累计保存种子: {stored_seed_count}")
    safe_print(f"输出: {SEED_PATH}")
    safe_print(f"失败清单: {FAILURE_PATH}")
    safe_print("\n本次 MBTI 分布:")
    for mbti, count in sorted(mbti_counts.items()):
        safe_print(f"  {mbti}: {count}")


if __name__ == "__main__":
    main()
