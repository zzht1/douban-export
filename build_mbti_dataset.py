"""
MBTI 特征提取与数据集构建。

对种子用户逐一爬取或复用本地缓存的书影音数据，
用 analyzer 提取特征向量，过滤低质量用户，并写出训练集文件。
"""

import analyzer as douban_analyzer
from web.scraper import scrape_user
from web import config
from mbti_features import (
    FEATURE_COLS,
    extract_features,
    merge_features,
    check_quality,
)
import argparse
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


OUTPUT_DIR = ROOT / "data" / "mbti_training"
FEATURES_DIR = OUTPUT_DIR / "features"
DOTENV_PATH = ROOT / ".env"


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


RESULT_DIR = ROOT / "result"


def build_dataset(
    seeds_path: Path,
    cookie: str = "",
    min_items: int = 30,
    max_users: int = 0,
) -> list[dict]:
    """对种子用户逐一采集并提取特征。"""
    seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
    if max_users > 0:
        seeds = seeds[:max_users]

    print(f"加载 {len(seeds)} 位种子用户")
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    dataset: list[dict] = []
    failures: list[dict] = []

    for index, seed in enumerate(seeds, start=1):
        uid = seed["user_id"]
        source_user_id = seed.get("source_user_id") or uid
        mbti = seed["mbti"]
        print(f"\n[{index}/{len(seeds)}] 处理 {uid} (MBTI: {mbti})...")

        feature_path = FEATURES_DIR / f"{uid}.json"
        features = None

        if feature_path.exists():
            print("  已有特征，直接加载")
            features = json.loads(feature_path.read_text(encoding="utf-8"))
        else:
            # 优先从 result/ 或 data/{uid}/ 加载已有分析 JSON
            for candidate_dir in [RESULT_DIR, config.DATA_DIR / uid]:
                ap = candidate_dir / f"{uid}_analysis.json"
                if ap.exists():
                    print(f"  从 {candidate_dir.name}/ 加载分析 JSON...")
                    try:
                        analysis = json.loads(ap.read_text(encoding="utf-8"))
                        features = merge_features(
                            extract_features(analysis, "movie"),
                            extract_features(analysis, "book"),
                        )
                        if features is not None:
                            feature_path.write_text(
                                json.dumps(
                                    features, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            print(f"  特征已缓存")
                    except Exception as exc:
                        print(f"  加载分析 JSON 失败: {exc}")
                    break

            # 如果找不到分析 JSON，但有 CSV，尝试运行分析器
            if features is None:
                csv_dir = config.DATA_DIR / uid
                if csv_dir.exists() and any(csv_dir.glob("*.csv")):
                    print("  发现 CSV 数据，运行分析器...")
                    try:
                        analysis = douban_analyzer.full_analysis(uid, csv_dir)
                        features = merge_features(
                            extract_features(analysis, "movie"),
                            extract_features(analysis, "book"),
                        )
                        if features is not None:
                            analysis["user_id"] = uid
                            (csv_dir / f"{uid}_analysis.json").write_text(
                                json.dumps(
                                    analysis, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            feature_path.write_text(
                                json.dumps(
                                    features, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            print("  分析完成并缓存")
                    except Exception as exc:
                        print(f"  分析失败: {exc}")

            if features is None:
                print("  爬取数据...")
                try:
                    scrape_result = scrape_user(
                        uid, cookie=cookie, progress=None)
                except Exception as exc:
                    print(f"  爬取失败: {exc}")
                    failures.append(
                        {
                            "user_id": uid,
                            "mbti": mbti,
                            "stage": "scrape",
                            "reason": str(exc),
                        }
                    )
                    continue

                total_items = sum(
                    len(block.get("collect", [])) + len(block.get("wish", []))
                    for block in scrape_result.values()
                )
                if total_items == 0:
                    print("  无数据，跳过")
                    failures.append(
                        {
                            "user_id": uid,
                            "mbti": mbti,
                            "stage": "scrape",
                            "reason": "未获取到任何数据",
                        }
                    )
                    continue

                print("  分析数据...")
                data_dir = config.DATA_DIR / uid
                analysis = douban_analyzer.full_analysis(uid, data_dir)
                features = merge_features(
                    extract_features(analysis, "movie"),
                    extract_features(analysis, "book"),
                )

                if features is not None:
                    feature_path.write_text(
                        json.dumps(features, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        ok, reason = check_quality(features, min_items)
        if not ok:
            print(f"  质量不足: {reason}")
            failures.append(
                {
                    "user_id": uid,
                    "mbti": mbti,
                    "stage": "quality",
                    "reason": reason,
                }
            )
            continue

        row = {"user_id": uid, "source_user_id": source_user_id,
               "mbti": mbti, **features}
        dataset.append(row)
        print(f"  [OK] 加入数据集 (共 {len(dataset)})")

    print(f"\n{'=' * 50}")
    failure_path = OUTPUT_DIR / "failed_users.json"
    failure_path.write_text(json.dumps(
        failures, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = OUTPUT_DIR / "dataset_manifest.json"
    manifest = {
        "seed_count": len(seeds),
        "dataset_count": len(dataset),
        "failure_count": len(failures),
        "min_items": min_items,
        "max_users": max_users,
        "dataset_user_ids": [row["user_id"] for row in dataset],
        "failed_user_ids": [row["user_id"] for row in failures],
    }
    manifest_path.write_text(json.dumps(
        manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"完成: {len(dataset)} 有效用户, {len(failures)} 跳过")
    print(f"失败清单: {failure_path}")
    print(f"清单: {manifest_path}")
    return dataset


def save_dataset_csv(dataset: list[dict], output_path: Path):
    """保存为 CSV。"""
    if not dataset:
        print("数据集为空，不保存")
        return

    fieldnames = ["user_id", "source_user_id", "mbti"] + FEATURE_COLS
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in dataset:
            writer.writerow(row)

    print(f"已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="MBTI 数据集构建")
    parser.add_argument("--cookie", default="", help="豆瓣 Cookie")
    parser.add_argument("--min-items", type=int, default=30, help="最低标记量")
    parser.add_argument("--max-users", type=int,
                        default=0, help="最大处理用户数（0=全部）")
    args = parser.parse_args()

    seeds_path = OUTPUT_DIR / "seeds.json"
    if not seeds_path.exists():
        print(f"未找到种子文件: {seeds_path}")
        print("请先运行: python collect_mbti_seeds.py")
        sys.exit(1)

    dataset = build_dataset(
        seeds_path=seeds_path,
        cookie=resolve_cookie(args.cookie),
        min_items=args.min_items,
        max_users=args.max_users,
    )

    if dataset:
        save_dataset_csv(dataset, OUTPUT_DIR / "dataset.csv")
        # split 由 augment_mbti_data.py 的 choose_holdout_split() 统一处理

    from collections import Counter

    counts = Counter(row["mbti"] for row in dataset)
    print("\nMBTI 分布:")
    for mbti, count in counts.most_common():
        print(f"  {mbti}: {count} ({count / len(dataset) * 100:.1f}%)")


if __name__ == "__main__":
    main()
