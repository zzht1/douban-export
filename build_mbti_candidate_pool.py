"""
从 result/*_analysis.json 生成未标注候选清单。

输出：
- data/mbti_training/unlabeled_candidates.json
- data/mbti_training/unlabeled_candidates.csv
- data/mbti_training/unlabeled_candidate_failures.json
- data/mbti_training/unlabeled_candidate_manifest.json
"""

from mbti_features import check_quality, extract_features, merge_features
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RESULT_DIR = ROOT / "result"
OUTPUT_DIR = ROOT / "data" / "mbti_training"
SEED_PATH = OUTPUT_DIR / "seeds.json"

CANDIDATE_JSON = OUTPUT_DIR / "unlabeled_candidates.json"
CANDIDATE_CSV = OUTPUT_DIR / "unlabeled_candidates.csv"
FAILURE_JSON = OUTPUT_DIR / "unlabeled_candidate_failures.json"
MANIFEST_JSON = OUTPUT_DIR / "unlabeled_candidate_manifest.json"

CANDIDATE_COLUMNS = [
    "user_id",
    "source_user_id",
    "analysis_file",
    "priority_group",
    "ns_band",
    "priority_score",
    "total_collected",
    "comment_rate",
    "avg_comment_length",
    "n_score",
    "era_median_year",
    "wish_ratio",
    "bulk_pct",
    "avg_rating",
    "five_star_pct",
    "quality_ok",
    "quality_reason",
    "note",
]


def load_seed_ids() -> set[str]:
    if not SEED_PATH.exists():
        return set()

    try:
        payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()

    seed_ids: set[str] = set()
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                user_id = item.get("user_id")
                if user_id:
                    seed_ids.add(str(user_id))
    return seed_ids


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def build_note(features: dict, quality_ok: bool, quality_reason: str) -> str:
    notes: list[str] = []
    total = safe_float(features.get("total_collected"))
    comment_rate = safe_float(features.get("comment_rate"))
    n_score = safe_float(features.get("n_score"))
    bulk_pct = safe_float(features.get("bulk_pct"))

    if quality_ok:
        notes.append("数据可用")
    else:
        notes.append(f"质量不足: {quality_reason}")

    if total >= 300:
        notes.append("数据量充足")
    elif total >= 100:
        notes.append("数据量中等")
    else:
        notes.append("数据量偏少")

    if comment_rate >= 0.6:
        notes.append("评论密度高")
    elif comment_rate >= 0.2:
        notes.append("有一定评论")
    else:
        notes.append("评论偏少")

    if n_score < 0.45:
        notes.append("NS 偏低")
    elif n_score <= 0.6:
        notes.append("NS 边界")
    else:
        notes.append("NS 偏高")

    if bulk_pct >= 20:
        notes.append("批量标记明显")

    return "；".join(notes)


def build_priority_group(quality_ok: bool, n_score: float, total_collected: float) -> str:
    if not quality_ok:
        return "low_volume"
    if total_collected < 100:
        return "low_volume"
    if n_score < 0.45:
        return "ns_low"
    if n_score <= 0.6:
        return "ns_boundary"
    return "ns_high"


def build_priority_score(features: dict) -> float:
    total = max(safe_float(features.get("total_collected")), 0.0)
    comment_rate = max(safe_float(features.get("comment_rate")), 0.0)
    n_score = safe_float(features.get("n_score"))
    coverage = math.log1p(total) * max(comment_rate, 0.05)
    boundary = max(0.0, 1.0 - abs(n_score - 0.5) * 2.0)
    return round(coverage * (0.6 + 0.4 * boundary), 6)


def build_candidate_record(path: Path, seed_ids: set[str]) -> tuple[dict | None, dict | None]:
    try:
        analysis = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, {
            "analysis_file": path.name,
            "stage": "parse",
            "reason": str(exc),
        }

    user_id = str(analysis.get("user_id")
                  or path.stem.replace("_analysis", ""))
    if user_id in seed_ids:
        return None, {
            "analysis_file": path.name,
            "user_id": user_id,
            "stage": "skip",
            "reason": "已在 seeds.json 中出现，跳过",
        }

    movie_features = extract_features(analysis, "movie")
    book_features = extract_features(analysis, "book")
    features = merge_features(movie_features, book_features)
    if not features:
        return None, {
            "analysis_file": path.name,
            "user_id": user_id,
            "stage": "features",
            "reason": "未提取到可用特征",
        }

    quality_ok, quality_reason = check_quality(features, min_items=30)
    n_score = safe_float(features.get("n_score"))
    total_collected = safe_float(features.get("total_collected"))
    priority_group = build_priority_group(quality_ok, n_score, total_collected)
    priority_score = build_priority_score(features)

    record = {
        "user_id": user_id,
        "source_user_id": analysis.get("source_user_id") or user_id,
        "analysis_file": path.name,
        "priority_group": priority_group,
        "ns_band": "low" if n_score < 0.45 else ("boundary" if n_score <= 0.6 else "high"),
        "priority_score": priority_score,
        "total_collected": total_collected,
        "comment_rate": safe_float(features.get("comment_rate")),
        "avg_comment_length": safe_float(features.get("avg_comment_length")),
        "n_score": n_score,
        "era_median_year": safe_float(features.get("era_median_year")),
        "wish_ratio": safe_float(features.get("wish_ratio")),
        "bulk_pct": safe_float(features.get("bulk_pct")),
        "avg_rating": safe_float(features.get("avg_rating")),
        "five_star_pct": safe_float(features.get("five_star_pct")),
        "quality_ok": quality_ok,
        "quality_reason": quality_reason,
        "note": build_note(features, quality_ok, quality_reason),
    }
    return record, None


def save_json(path: Path, payload: object):
    path.write_text(json.dumps(payload, ensure_ascii=False,
                    indent=2), encoding="utf-8")


def save_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seed_ids = load_seed_ids()

    candidates: list[dict] = []
    failures: list[dict] = []

    analysis_files = sorted(RESULT_DIR.glob("*_analysis.json"))
    for path in analysis_files:
        candidate, failure = build_candidate_record(path, seed_ids)
        if candidate is not None:
            candidates.append(candidate)
        if failure is not None:
            failures.append(failure)

    priority_order = {
        "ns_low": 0,
        "ns_boundary": 1,
        "ns_high": 2,
        "low_volume": 3,
    }
    candidates.sort(
        key=lambda row: (
            priority_order.get(row["priority_group"], 9),
            -row["priority_score"],
            -row["total_collected"],
            row["user_id"],
        )
    )

    save_json(CANDIDATE_JSON, candidates)
    save_csv(CANDIDATE_CSV, candidates)
    save_json(FAILURE_JSON, failures)

    manifest = {
        "analysis_files": len(analysis_files),
        "seed_ids": sorted(seed_ids),
        "candidate_count": len(candidates),
        "failure_count": len(failures),
        "priority_group_counts": {
            group: sum(
                1 for row in candidates if row["priority_group"] == group)
            for group in ["ns_low", "ns_boundary", "ns_high", "low_volume"]
        },
        "top_candidates": [
            {
                "user_id": row["user_id"],
                "priority_group": row["priority_group"],
                "n_score": row["n_score"],
                "total_collected": row["total_collected"],
            }
            for row in candidates[:5]
        ],
        "output_files": {
            "json": str(CANDIDATE_JSON),
            "csv": str(CANDIDATE_CSV),
            "failures": str(FAILURE_JSON),
        },
    }
    save_json(MANIFEST_JSON, manifest)

    print(f"候选数: {len(candidates)}")
    print(f"失败数: {len(failures)}")
    print(f"输出: {CANDIDATE_JSON}")
    print(f"失败清单: {FAILURE_JSON}")


if __name__ == "__main__":
    main()
