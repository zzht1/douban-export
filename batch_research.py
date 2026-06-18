"""
批量爬取豆瓣用户书影音数据 + 运行分析

用于调研"书影音 MBTI"维度设计，对多个代表性用户进行数据采集和分析。
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime

# 项目根目录（douban-export/）
PROJECT_DIR = Path(__file__).resolve().parent
EXPORT_SCRIPT = PROJECT_DIR / "douban_movie_export.py"
ANALYZER_SCRIPT = PROJECT_DIR / "analyzer.py"

# 数据输出目录
DATA_DIR = PROJECT_DIR / "result"

# 所有待调研用户
USERS = [
    # --- 用户提供的 12 人 ---
    {"id": "156883939",     "source": "user",     "note": ""},
    {"id": "feizhaizhangmen", "source": "user",     "note": ""},
    {"id": "aada",          "source": "user",      "note": ""},
    {"id": "4075628",       "source": "user",      "note": ""},
    {"id": "wzfeng2019",    "source": "user",      "note": ""},
    {"id": "171133816",     "source": "user",      "note": ""},
    {"id": "xilouchen",     "source": "user",      "note": ""},
    {"id": "102454210",     "source": "user",      "note": ""},
    {"id": "film101",       "source": "user",      "note": ""},
    {"id": "Sacronlau",     "source": "user",      "note": ""},
    {"id": "cabaret",       "source": "user",      "note": ""},
    {"id": "tjz230",        "source": "user",      "note": ""},
    # --- 我找的 5 人 ---
    {"id": "fangyunan",     "source": "research",  "note": "万部影迷+书影双修"},
    {"id": "Schopenhauer126", "source": "research", "note": "深度影评人(叔本华)"},
    {"id": "1087580",       "source": "research",  "note": "文艺读者(子文东)"},
    {"id": "shunian",       "source": "research",  "note": "杂食型(Lazy念念)"},
    {"id": "zionius",       "source": "research",  "note": "专精型(翻译研究)"},
]


def run_export(user_id: str, output_dir: Path) -> bool:
    """运行导出脚本，抓取该用户的书影音 CSV。"""
    print(f"\n{'='*60}")
    print(f"[EXPORT] 用户: {user_id}")
    print(f"{'='*60}")

    cmd = [
        sys.executable, str(EXPORT_SCRIPT),
        user_id,
        "--type", "all",
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(output_dir),
            capture_output=False,
            text=True,
            timeout=3600,  # 1小时超时（大用户可能需要很久）
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[!] 导出超时: {user_id}")
        return False
    except Exception as e:
        print(f"[!] 导出失败: {user_id} - {e}")
        return False


def run_analyze(user_id: str, data_dir: Path) -> bool:
    """运行分析脚本。"""
    print(f"\n[ANALYZE] 用户: {user_id}")

    cmd = [
        sys.executable, str(ANALYZER_SCRIPT),
        user_id,
        "--dir", str(data_dir),
        "--output", str(data_dir / f"{user_id}_analysis.json"),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(data_dir),
            capture_output=False,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[!] 分析超时: {user_id}")
        return False
    except Exception as e:
        print(f"[!] 分析失败: {user_id} - {e}")
        return False


def count_csv_files(user_id: str, data_dir: Path) -> dict:
    """统计该用户的 CSV 文件数量和内容行数。"""
    result = {}
    for suffix in ["movies", "movie_wish", "books", "book_wish"]:
        csv_path = data_dir / f"{user_id}_{suffix}.csv"
        if csv_path.exists():
            with open(csv_path, encoding="utf-8-sig") as f:
                lines = sum(1 for _ in f) - 1  # 减去表头
            result[suffix] = max(lines, 0)
        else:
            result[suffix] = 0
    return result


def main():
    DATA_DIR.mkdir(exist_ok=True)

    # 检查是否已有部分数据（支持断点续跑）
    skip_users = set()
    for user in USERS:
        uid = user["id"]
        analysis_path = DATA_DIR / f"{uid}_analysis.json"
        if analysis_path.exists():
            print(f"[SKIP] {uid} 已有分析结果，跳过")
            skip_users.add(uid)

    total = len(USERS)
    done = 0
    failed = []
    summary = []

    print(f"\n{'#'*60}")
    print(f"# 豆瓣书影音调研 — 批量数据采集")
    print(f"# 共 {total} 个用户，跳过 {len(skip_users)} 个已完成")
    print(f"# 数据目录: {DATA_DIR}")
    print(f"# 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}\n")

    for i, user in enumerate(USERS, 1):
        uid = user["id"]

        if uid in skip_users:
            # 读取已有的分析结果做摘要
            analysis_path = DATA_DIR / f"{uid}_analysis.json"
            with open(analysis_path, encoding="utf-8") as f:
                data = json.load(f)
            counts = count_csv_files(uid, DATA_DIR)
            summary.append({
                "user_id": uid,
                "source": user["source"],
                "note": user["note"],
                "status": "ok (cached)",
                "counts": counts,
            })
            continue

        print(f"\n[{i}/{total}] 处理用户: {uid} ({user.get('note', '')})")
        start_time = time.time()

        # Step 1: 导出（如果 CSV 已存在则跳过）
        existing_counts = count_csv_files(uid, DATA_DIR)
        if sum(existing_counts.values()) > 0:
            print(f"  [SKIP] CSV 已存在，跳过导出: {existing_counts}")
            export_ok = True
            counts = existing_counts
        else:
            export_ok = run_export(uid, DATA_DIR)

        # Step 2: 分析（不管 count 多少都跑，让 analyzer 自己判断）
        analyze_ok = run_analyze(uid, DATA_DIR)

        # 导出后再统计
        counts = count_csv_files(uid, DATA_DIR)
        total_items = sum(counts.values())

        if total_items == 0 and not export_ok:
            print(f"[!] 用户 {uid} 无任何数据，可能是私密账号或ID错误")
            failed.append(uid)
            summary.append({
                "user_id": uid,
                "source": user["source"],
                "note": user["note"],
                "status": "no_data",
                "counts": counts,
            })
            continue

        elapsed = time.time() - start_time
        status = "ok" if (export_ok and analyze_ok) else "partial"

        summary.append({
            "user_id": uid,
            "source": user["source"],
            "note": user["note"],
            "status": status,
            "counts": counts,
            "elapsed_seconds": round(elapsed, 1),
        })

        print(f"[{status.upper()}] {uid}: 电影={counts.get('movies', 0)}, "
              f"想看={counts.get('movie_wish', 0)}, "
              f"图书={counts.get('books', 0)}, "
              f"想读={counts.get('book_wish', 0)}, "
              f"耗时={elapsed:.0f}s")

        done += 1

        # 用户间间隔，避免被封
        if i < total and uid not in skip_users:
            wait = 5
            print(f"  等待 {wait}s 避免频率限制...")
            time.sleep(wait)

    # 输出汇总
    print(f"\n\n{'#'*60}")
    print(f"# 汇总")
    print(f"{'#'*60}")
    print(f"\n{'用户ID':<20} {'来源':<10} {'电影':>6} {'想看':>6} {'图书':>6} {'想读':>6} {'状态'}")
    print("-" * 75)
    for s in summary:
        c = s["counts"]
        print(f"{s['user_id']:<20} {s['source']:<10} "
              f"{c.get('movies', 0):>6} {c.get('movie_wish', 0):>6} "
              f"{c.get('books', 0):>6} {c.get('book_wish', 0):>6} "
              f"{s['status']}")

    # 保存汇总 JSON
    summary_path = DATA_DIR / "research_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_users": total,
            "success": sum(1 for s in summary if s["status"].startswith("ok")),
            "failed": len(failed),
            "users": summary,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n汇总已保存: {summary_path}")


if __name__ == "__main__":
    main()
