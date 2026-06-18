"""
后台任务管理器

使用 ThreadPoolExecutor 管理分析任务，跟踪进度状态。
"""

from web.llm_report import generate_report
from web.mbti_predictor import predict_mbti
from web.scraper import scrape_user, parse_user_id
from web import config
import analyzer as douban_analyzer
import json
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path，以便 import analyzer
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ── 任务状态存储 ──────────────────────────────────────────

_tasks: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)


def get_task(task_id: str) -> dict | None:
    """获取任务状态。"""
    return _tasks.get(task_id)


def get_all_tasks() -> list[dict]:
    """获取所有任务（摘要）。"""
    return [
        {
            "task_id": tid,
            "user_id": t["user_id"],
            "status": t["status"],
            "phase": t["phase"],
            "percent": t["percent"],
            "created_at": t["created_at"],
        }
        for tid, t in _tasks.items()
    ]


# ── 缓存检查 ──────────────────────────────────────────────

def _check_cache(user_id: str) -> Path | None:
    """检查是否有未过期的分析缓存，返回 JSON 路径或 None。"""
    json_path = config.DATA_DIR / user_id / f"{user_id}_analysis.json"
    if not json_path.exists():
        return None

    # 检查文件年龄
    mtime = json_path.stat().st_mtime
    age_hours = (time.time() - mtime) / 3600
    if age_hours > config.CACHE_TTL_HOURS:
        return None

    return json_path


def _build_user_paths(user_id: str) -> dict[str, Path]:
    """构建用户相关文件路径。"""
    data_dir = config.DATA_DIR / user_id
    return {
        "data_dir": data_dir,
        "analysis": data_dir / f"{user_id}_analysis.json",
        "report": data_dir / f"{user_id}_report.html",
        "card": data_dir / f"{user_id}_card.html",
        "scrape_meta": data_dir / f"{user_id}_scrape_meta.json",
        "failure": data_dir / f"{user_id}_failure.json",
    }


def _write_json(path: Path, payload: dict):
    """写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_json(path: Path) -> dict:
    """读取 JSON 文件。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _build_result_payload(user_id: str) -> dict:
    """构建任务结果中的文件路径。"""
    paths = _build_user_paths(user_id)
    return {
        "user_id": user_id,
        "analysis_path": str(paths["analysis"]),
        "report_path": str(paths["report"]),
        "card_path": str(paths["card"]),
        "scrape_meta_path": str(paths["scrape_meta"]),
        "failure_path": str(paths["failure"]),
    }


def _ensure_report_assets(user_id: str, analysis: dict) -> dict:
    """确保报告和卡片文件存在。"""
    paths = _build_user_paths(user_id)
    paths["data_dir"].mkdir(parents=True, exist_ok=True)

    if not paths["report"].exists():
        report_html = generate_report(analysis)
        paths["report"].write_text(report_html, encoding="utf-8")

    if not paths["card"].exists():
        card_html = _generate_card(user_id, analysis)
        if card_html:
            paths["card"].write_text(card_html, encoding="utf-8")

    return _build_result_payload(user_id)


def _load_cached_result(user_id: str) -> dict | None:
    """加载缓存结果，并补齐缺失的报告文件。"""
    analysis_path = _check_cache(user_id)
    if not analysis_path:
        return None

    try:
        analysis = _load_json(analysis_path)
        analysis.setdefault("user_id", user_id)
        return _ensure_report_assets(user_id, analysis)
    except Exception:
        return None


def _persist_failure(user_id: str, stage: str, message: str, *, error: str | None = None, scrape_meta: dict | None = None):
    """记录最近一次失败，便于人工追踪。"""
    paths = _build_user_paths(user_id)
    payload = {
        "user_id": user_id,
        "stage": stage,
        "message": message,
        "error": error,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scrape_meta": scrape_meta or {},
    }
    _write_json(paths["failure"], payload)


def _clear_failure_record(user_id: str):
    """清理历史失败记录。"""
    failure_path = _build_user_paths(user_id)["failure"]
    if failure_path.exists():
        failure_path.unlink()


def _build_empty_data_error(scrape_meta: dict) -> str:
    """根据抓取元数据生成更清晰的空数据错误。"""
    errors = scrape_meta.get("errors", [])
    if not errors:
        return "未获取到任何数据，请检查用户 ID 是否正确，或稍后重试。"

    forbidden_count = sum(1 for item in errors if item.get("kind") == "forbidden")
    timeout_count = sum(1 for item in errors if item.get("kind") == "timeout")
    network_count = sum(1 for item in errors if item.get("kind") == "network_error")

    if forbidden_count:
        if scrape_meta.get("cookie_provided"):
            return "未获取到任何数据。豆瓣返回了 403，提供的 Cookie 可能已失效，或该页面当前拒绝访问。"
        return "未获取到任何数据。豆瓣返回了 403，通常是因为未提供登录 Cookie，或匿名访问受限。"
    if timeout_count and not network_count:
        return "未获取到任何数据。请求超时，豆瓣响应较慢，建议稍后重试。"
    if network_count or timeout_count:
        return "未获取到任何数据。请求过程中发生网络异常，建议稍后重试。"
    return "未获取到任何数据，请检查用户 ID 是否正确，或尝试提供 Cookie。"


# ── 任务执行 ──────────────────────────────────────────────

def _update_progress(task_id: str, phase: str, percent: int, message: str):
    """更新任务进度。"""
    t = _tasks.get(task_id)
    if t:
        t["phase"] = phase
        t["percent"] = min(percent, 100)
        t["message"] = message
        t["logs"].append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "phase": phase,
            "message": message,
        })


def _run_task(task_id: str, user_id: str, cookie: str):
    """执行完整的分析流水线。"""
    t = _tasks[task_id]

    try:
        # 每次从头开始，清除旧数据
        delete_user_data(user_id)

        paths = _build_user_paths(user_id)
        data_dir = paths["data_dir"]

        # ── 阶段 1: 爬取 ──
        _update_progress(task_id, "scraping", 0, "开始爬取豆瓣数据...")

        def progress_cb(phase, percent, message):
            _update_progress(task_id, phase, percent, message)

        scrape_result = scrape_user(
            user_id,
            cookie=cookie,
            progress=progress_cb,
        )
        scrape_meta = scrape_result.get("_meta", {})
        _write_json(paths["scrape_meta"], scrape_meta)

        # 检查是否爬到任何数据
        total_items = sum(
            len(v.get("collect", [])) + len(v.get("wish", []))
            for key, v in scrape_result.items()
            if key != "_meta"
        )
        if total_items == 0:
            t["status"] = "error"
            t["error"] = _build_empty_data_error(scrape_meta)
            _persist_failure(
                user_id,
                "scraping",
                t["error"],
                scrape_meta=scrape_meta,
            )
            _update_progress(task_id, "error", 0, t["error"])
            return

        if scrape_meta.get("has_errors"):
            _update_progress(
                task_id,
                "scraping_done",
                80,
                f"爬取完成，但有 {len(scrape_meta.get('errors', []))} 个请求失败，将继续分析已抓到的数据。",
            )

        # ── 阶段 2: 分析 ──
        _update_progress(task_id, "analyzing", 82, "正在分析数据...")

        analysis = douban_analyzer.full_analysis(user_id, data_dir)
        analysis["user_id"] = user_id
        analysis["analysis_date"] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S")
        analysis["scrape_meta"] = scrape_meta

        # MBTI 预测
        try:
            mbti_result = predict_mbti(analysis)
            analysis["mbti_prediction"] = mbti_result
            if mbti_result.get("mbti"):
                _update_progress(
                    task_id, "analyzing", 88,
                    f"MBTI 预测: {mbti_result['mbti']} (置信度 {mbti_result['confidence']:.0%})")
        except Exception as e:
            analysis["mbti_prediction"] = {"mbti": None, "error": str(e)}

        # 保存分析 JSON
        _write_json(paths["analysis"], analysis)

        _update_progress(task_id, "analyzing", 90, "分析完成，正在生成报告...")

        # ── 阶段 3: 生成报告 ──
        _update_progress(task_id, "generating_report", 92, "正在生成分析报告...")

        report_html = generate_report(analysis)

        # 保存报告
        paths["report"].write_text(report_html, encoding="utf-8")

        # 生成社交卡片数据
        card_html = _generate_card(user_id, analysis)
        if card_html:
            paths["card"].write_text(card_html, encoding="utf-8")

        # ── 完成 ──
        t["status"] = "done"
        t["result"] = _build_result_payload(user_id)
        _clear_failure_record(user_id)
        _update_progress(task_id, "done", 100, "分析完成！")

    except Exception as e:
        t["status"] = "error"
        t["error"] = str(e)
        _persist_failure(user_id, "pipeline", "分析流程执行失败", error=str(e))
        _update_progress(task_id, "error", t["percent"], f"出错: {e}")


def _generate_card(user_id: str, analysis: dict) -> str:
    """生成社交卡片 HTML。"""
    social = analysis.get("social_card", {})
    if not social:
        return ""

    # 提取核心数据
    movie = social.get("movie", {})
    book = social.get("book", {})

    movie_total = movie.get("total", 0)
    book_total = book.get("total", 0)
    movie_avg = movie.get("avg_rating", "—")
    book_avg = book.get("avg_rating", "—")

    # 生成卡片 HTML
    card_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{user_id} 的书影音画像</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    width: 420px;
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #e0e0e0;
    padding: 30px 20px;
}}
.card-header {{
    text-align: center;
    margin-bottom: 24px;
}}
.card-header h1 {{
    font-size: 22px;
    color: #d4af37;
    font-weight: 600;
    margin-bottom: 8px;
}}
.card-header .subtitle {{
    font-size: 13px;
    color: #888;
}}
.stats-row {{
    display: flex;
    justify-content: center;
    gap: 30px;
    margin-bottom: 24px;
}}
.stat-item {{
    text-align: center;
}}
.stat-value {{
    font-size: 28px;
    font-weight: 700;
    color: #d4af37;
}}
.stat-label {{
    font-size: 12px;
    color: #999;
    margin-top: 4px;
}}
.section {{
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(212,175,55,0.2);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
}}
.section-title {{
    font-size: 15px;
    color: #d4af37;
    margin-bottom: 10px;
    font-weight: 600;
}}
.top-item {{
    font-size: 13px;
    padding: 4px 0;
    color: #ccc;
}}
.top-item .title {{
    color: #e0e0e0;
}}
.top-item .rating {{
    color: #d4af37;
    font-size: 12px;
}}
.card-footer {{
    text-align: center;
    margin-top: 20px;
    font-size: 11px;
    color: #666;
}}
</style>
</head>
<body>
<div class="card-header">
    <h1>{user_id} 的书影音画像</h1>
    <div class="subtitle">由 Douban Insight 生成</div>
</div>

<div class="stats-row">
    <div class="stat-item">
        <div class="stat-value">{movie_total}</div>
        <div class="stat-label">部观影</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{movie_avg}</div>
        <div class="stat-label">影均分</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{book_total}</div>
        <div class="stat-label">本阅读</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{book_avg}</div>
        <div class="stat-label">书均分</div>
    </div>
</div>
"""

    # Top 5 电影
    movie_top = movie.get("top5", [])
    if movie_top:
        card_html += '<div class="section"><div class="section-title">标志性观影</div>'
        for item in movie_top[:5]:
            title = item.get("title", "")
            rating = item.get("rating", "")
            stars = "⭐" * int(rating) if rating else ""
            card_html += f'<div class="top-item"><span class="title">{title}</span> <span class="rating">{stars}</span></div>'
        card_html += "</div>\n"

    # Top 5 图书
    book_top = book.get("top5", [])
    if book_top:
        card_html += '<div class="section"><div class="section-title">标志性阅读</div>'
        for item in book_top[:5]:
            title = item.get("title", "")
            rating = item.get("rating", "")
            stars = "⭐" * int(rating) if rating else ""
            card_html += f'<div class="top-item"><span class="title">{title}</span> <span class="rating">{stars}</span></div>'
        card_html += "</div>\n"

    card_html += f"""
<div class="card-footer">
    生成于 {datetime.now().strftime("%Y-%m-%d")} · Douban Insight
</div>
</body>
</html>"""

    return card_html


# ── 数据管理 ──────────────────────────────────────────────

def delete_user_data(user_id: str) -> bool:
    """删除指定用户的所有缓存数据。

    清除 data/{user_id}/ 目录下的所有文件（CSV、分析结果、报告、卡片）。
    返回是否成功删除。
    """
    user_dir = config.DATA_DIR / user_id
    if user_dir.exists():
        shutil.rmtree(user_dir)
        return True
    return False


def get_user_data_info(user_id: str) -> dict:
    """获取指定用户的缓存数据信息。"""
    user_dir = config.DATA_DIR / user_id
    if not user_dir.exists():
        return {"exists": False}

    files = list(user_dir.glob("*"))
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    analysis_path = user_dir / f"{user_id}_analysis.json"

    return {
        "exists": True,
        "file_count": len(files),
        "total_size_kb": round(total_size / 1024, 1),
        "has_analysis": analysis_path.exists(),
        "last_modified": datetime.fromtimestamp(
            max(f.stat().st_mtime for f in files if f.is_file())
        ).strftime("%Y-%m-%d %H:%M") if files else None,
    }


# ── 创建任务 ──────────────────────────────────────────────

def create_task(user_input: str, cookie: str = "", force: bool = False) -> dict:
    """创建一个新的分析任务。

    每次运行都从头爬取，不保留旧数据。

    参数:
        user_input: 用户输入的豆瓣 ID 或 URL
        cookie: 可选的 Cookie 字符串
        force: 保留参数，兼容旧调用

    返回:
        {"task_id": str, "user_id": str, "status": str}
    """
    user_id = parse_user_id(user_input)
    task_id = str(uuid.uuid4())[:8]

    if not force:
        cached_result = _load_cached_result(user_id)
        if cached_result:
            _tasks[task_id] = {
                "user_id": user_id,
                "status": "done",
                "phase": "done",
                "percent": 100,
                "message": f"命中 {config.CACHE_TTL_HOURS} 小时内缓存，直接返回上次结果。",
                "logs": [{"time": datetime.now().strftime("%H:%M:%S"),
                          "phase": "done", "message": "命中缓存，跳过重新爬取"}],
                "created_at": datetime.now().isoformat(),
                "result": cached_result,
                "error": None,
            }
            return {"task_id": task_id, "user_id": user_id, "status": "done", "cached": True}

    # 创建新任务
    _tasks[task_id] = {
        "user_id": user_id,
        "status": "running",
        "phase": "queued",
        "percent": 0,
        "message": "任务已创建，等待执行..." if not force else "任务已创建，将强制重新抓取...",
        "logs": [{"time": datetime.now().strftime("%H:%M:%S"),
                  "phase": "queued", "message": "任务已创建" if not force else "任务已创建（强制重跑）"}],
        "created_at": datetime.now().isoformat(),
        "result": None,
        "error": None,
    }

    # 提交到线程池
    _executor.submit(_run_task, task_id, user_id, cookie)

    return {"task_id": task_id, "user_id": user_id, "status": "running"}
