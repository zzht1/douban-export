"""
Flask 主应用

路由：
  GET  /                     → 首页
  POST /api/analyze           → 创建分析任务
  GET  /api/status/<task_id>  → 任务进度
  GET  /report/<task_id>      → 报告页
  GET  /api/card/<task_id>    → 社交卡片 HTML
"""

from web.worker import create_task, get_task, get_all_tasks, delete_user_data, get_user_data_info
from web import config
from flask import Flask, jsonify, render_template, request, send_file
import json
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)


# ── 页面路由 ──────────────────────────────────────────────

@app.route("/")
def index():
    """首页：输入表单。"""
    return render_template("index.html")


@app.route("/report/<task_id>")
def report_page(task_id: str):
    """报告展示页。"""
    task = get_task(task_id)
    if not task:
        return "任务不存在", 404
    if task["status"] == "error":
        return render_template("result.html", task=task, task_id=task_id, error=task.get("error"))
    if task["status"] != "done":
        return render_template("result.html", task=task, task_id=task_id, loading=True)

    # 加载报告 HTML 和分析数据
    report_html = ""
    analysis = None
    result = task.get("result", {})

    report_path = result.get("report_path", "")
    if report_path and Path(report_path).exists():
        report_html = Path(report_path).read_text(encoding="utf-8")

    analysis_path = result.get("analysis_path", "")
    if analysis_path and Path(analysis_path).exists():
        with open(analysis_path, encoding="utf-8") as f:
            analysis = json.load(f)

    return render_template(
        "result.html",
        task=task,
        task_id=task_id,
        report_html=report_html,
        analysis=analysis,
    )


# ── API 路由 ──────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """创建分析任务。

    Body (JSON):
        {"user": "豆瓣用户ID或URL", "cookie": "可选Cookie", "force": false}
    """
    data = request.get_json()
    if not data or not data.get("user"):
        return jsonify({"error": "请提供豆瓣用户名或链接"}), 400

    user_input = data["user"].strip()
    cookie = data.get("cookie", "").strip()
    force = data.get("force", False)

    result = create_task(user_input, cookie, force=force)
    return jsonify(result)


@app.route("/api/status/<task_id>")
def api_status(task_id: str):
    """获取任务状态。"""
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    return jsonify({
        "task_id": task_id,
        "user_id": task["user_id"],
        "status": task["status"],
        "phase": task["phase"],
        "percent": task["percent"],
        "message": task["message"],
        "logs": task.get("logs", [])[-10:],  # 最近 10 条日志
        "error": task.get("error"),
    })


@app.route("/api/card/<task_id>")
def api_card(task_id: str):
    """返回社交卡片 HTML。"""
    task = get_task(task_id)
    if not task or task["status"] != "done":
        return "卡片不可用", 404

    card_path = task.get("result", {}).get("card_path", "")
    if not card_path or not Path(card_path).exists():
        return "卡片未生成", 404

    return Path(card_path).read_text(encoding="utf-8")


@app.route("/api/download/card/<task_id>")
def download_card(task_id: str):
    """下载社交卡片 HTML。"""
    task = get_task(task_id)
    if not task or task["status"] != "done":
        return "卡片不可用", 404

    card_path = Path(task.get("result", {}).get("card_path", ""))
    if not card_path.exists():
        return "卡片未生成", 404

    return send_file(
        card_path,
        as_attachment=True,
        download_name=f"{task['user_id']}_card.html",
        mimetype="text/html",
    )


@app.route("/api/download/report/<task_id>")
def download_report(task_id: str):
    """下载报告 HTML。"""
    task = get_task(task_id)
    if not task or task["status"] != "done":
        return "报告不可用", 404

    report_path = Path(task.get("result", {}).get("report_path", ""))
    if not report_path.exists():
        return "报告未生成", 404

    return send_file(
        report_path,
        as_attachment=True,
        download_name=f"{task['user_id']}_report.html",
        mimetype="text/html",
    )


@app.route("/api/tasks")
def api_tasks():
    """列出所有任务（调试用）。"""
    return jsonify(get_all_tasks())


@app.route("/api/data/<user_id>", methods=["GET"])
def api_data_info(user_id: str):
    """获取指定用户的缓存数据信息。"""
    info = get_user_data_info(user_id)
    return jsonify(info)


@app.route("/api/data/<user_id>", methods=["DELETE"])
def api_delete_data(user_id: str):
    """删除指定用户的所有缓存数据（隐私权利）。"""
    deleted = delete_user_data(user_id)
    return jsonify({"deleted": deleted, "user_id": user_id})


# ── 启动 ──────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[*] Douban Insight Web 启动中...")
    print(f"    地址: http://{config.HOST}:{config.PORT}")
    print(f"    数据目录: {config.DATA_DIR}")
    print(f"    LLM: {'已配置' if config.LLM_API_KEY else '未配置（将使用模板报告）'}")
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=config.DEBUG,
    )
