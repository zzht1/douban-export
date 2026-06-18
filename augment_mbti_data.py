"""
MBTI 数据增强

用现有真实用户特征向量，通过添加高斯噪声生成合成样本。
每个真实用户生成 N 个变体，保持 MBTI 标签不变。
欠代表类型（S、E、P）自动获得更多增强样本。

用法:
    python augment_mbti_data.py
    python augment_mbti_data.py --variants 8   # 调整每个用户的变体数
"""
from mbti_features import FEATURE_COLS
import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DATA_DIR = ROOT / "data" / "mbti_training"


def load_dataset(path: Path) -> list[dict]:
    """加载现有数据集 CSV。"""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def augment_sample(
    row: dict,
    noise_scale: float = 0.15,
    feature_stats: dict | None = None,
    rng: random.Random | None = None,
) -> dict:
    """为一条真实样本生成一个带噪声的合成变体。

    如果提供 feature_stats (每个特征的中位数和标准差)，则用
    统计量来校准噪声，避免特征尺度不一致。

    rng: 可传入固定种子的 Random 实例以保证可复现。
    """
    _rng = rng or random
    source_user_id = row.get("source_user_id") or row["user_id"]
    new = {
        "user_id": f"syn_{source_user_id}_{_rng.randint(1000, 9999)}",
        "source_user_id": source_user_id,
        "mbti": row["mbti"],
    }
    for col in FEATURE_COLS:
        raw = row.get(col, "")
        val = float(raw) if raw else 0.0
        # 使用特征统计量校准噪声
        if feature_stats and col in feature_stats:
            std = feature_stats[col]["std"]
            scale = max(std * noise_scale, abs(val) * 0.05 + 0.01)
        else:
            scale = abs(val) * noise_scale + 0.01
        noise = _rng.gauss(0, scale)
        new_val = val + noise
        # 约束范围
        if col in ("comment_rate", "wish_ratio", "bulk_pct", "five_star_pct",
                   "f_pct_top_rated", "t_pct_top_rated"):
            new_val = max(0.0, min(1.0, new_val))
        elif col == "total_collected":
            new_val = max(10, int(new_val))
        elif col == "era_median_year":
            new_val = max(1950, min(2026, new_val))
        elif col in ("n_score", "f_score", "t_score"):
            new_val = max(0.0, min(1.0, new_val))
        elif col in ("f_lift", "t_lift"):
            pass  # 可以是负数
        elif col == "rating_std":
            new_val = max(0.0, new_val)
        elif col == "avg_rating":
            new_val = max(1.0, min(5.0, new_val))
        new[col] = round(new_val, 4)
    return new


def compute_feature_stats(rows: list[dict]) -> dict:
    """计算每个特征的中位数和标准差。"""
    stats = {}
    for col in FEATURE_COLS:
        values = []
        for row in rows:
            raw = row.get(col, "")
            if raw:
                try:
                    values.append(float(raw))
                except ValueError:
                    pass
        if values:
            stats[col] = {
                "median": float(np.median(values)),
                "std": float(np.std(values)),
                "mean": float(np.mean(values)),
            }
    return stats


def compute_type_weights(rows: list[dict]) -> dict[str, int]:
    """计算每个 MBTI 类型的增强权重，欠代表类型获得更多变体。"""
    counts = Counter(row["mbti"] for row in rows)
    if not counts:
        return {}

    # 按维度统计
    dim_counts = [{}, {}, {}, {}]
    for mbti, cnt in counts.items():
        for idx, letter in enumerate(mbti):
            dim_counts[idx][letter] = dim_counts[idx].get(letter, 0) + cnt

    # 计算每个类型的稀缺度得分
    weights = {}
    for mbti in counts:
        score = 1.0
        for idx, letter in enumerate(mbti):
            total = sum(dim_counts[idx].values())
            letter_count = dim_counts[idx].get(letter, 0)
            if total > 0:
                rarity = 1.0 - (letter_count / total)
                score += rarity * 2  # 稀缺维度加权
        weights[mbti] = max(1, round(score))
    return weights


def dimension_coverage(rows: list[dict]) -> int:
    """计算一组样本对 4 个维度的覆盖度。"""
    if not rows:
        return 0
    score = 0
    for idx in range(4):
        score += len({row["mbti"][idx] for row in rows})
    return score


def choose_holdout_split(
    real_data: list[dict],
    val_size: int,
    test_size: int,
    max_trials: int = 2000,
    rng: random.Random | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """在真实用户层面选择覆盖度更好的 train/val/test 划分。"""
    _rng = rng or random
    n = len(real_data)
    if n <= val_size + test_size:
        raise ValueError("真实样本不足，无法划分训练/验证/测试集")

    indices = list(range(n))
    best = None
    best_score = None

    for _ in range(max_trials):
        shuffled = indices[:]
        _rng.shuffle(shuffled)
        test_idx = shuffled[:test_size]
        val_idx = shuffled[test_size:test_size + val_size]
        train_idx = shuffled[test_size + val_size:]

        train_rows = [real_data[i] for i in train_idx]
        val_rows = [real_data[i] for i in val_idx]
        test_rows = [real_data[i] for i in test_idx]

        score = (
            dimension_coverage(train_rows) * 100
            + dimension_coverage(test_rows) * 10
            + dimension_coverage(val_rows)
        )

        # 偏向把真实样本更多地留给训练集
        score += len(train_rows)

        if best_score is None or score > best_score:
            best_score = score
            best = (train_rows, val_rows, test_rows)

    if best is None:
        raise RuntimeError("无法找到有效划分")
    return best


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    """写 CSV。"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def summarize_split(name: str, rows: list[dict]):
    """打印划分摘要。"""
    from collections import Counter

    print(f"\n{name}: {len(rows)}")
    print(f"  MBTI: {dict(Counter(row['mbti'] for row in rows))}")
    for idx, dim in enumerate(["IE", "NS", "FT", "JP"]):
        print(f"  {dim}: {dict(Counter(row['mbti'][idx] for row in rows))}")


def main():
    parser = argparse.ArgumentParser(description="MBTI 数据增强")
    parser.add_argument("--variants", type=int, default=0, help="每个真实用户的基础变体数 (0=自动)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（保证可复现）")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    np.random.seed(args.seed)

    dataset_path = DATA_DIR / "dataset.csv"
    if not dataset_path.exists():
        print(f"未找到数据集: {dataset_path}")
        return

    real_data = load_dataset(dataset_path)
    for row in real_data:
        row["source_user_id"] = row.get("source_user_id") or row["user_id"]
    n_real = len(real_data)
    print(f"真实样本: {n_real}")

    # 自适应变体数：真实样本越多，增强比例越低
    if args.variants > 0:
        base_variants = args.variants
    else:
        if n_real < 30:
            base_variants = 8  # 少样本时高增强
        elif n_real < 50:
            base_variants = 5
        elif n_real < 100:
            base_variants = 3
        else:
            base_variants = 2  # 充足样本时低增强
        print(f"自动变体数: {base_variants} (基于 {n_real} 真实样本)")

    # 计算特征统计量和类型权重
    feature_stats = compute_feature_stats(real_data)
    type_weights = compute_type_weights(real_data)
    print(f"类型权重: {type_weights}")

    val_size = max(1, round(len(real_data) * 0.2))
    test_size = max(2, round(len(real_data) * 0.2))
    if val_size + test_size >= len(real_data):
        val_size = 1
        test_size = 2

    train_real, val_real, test_real = choose_holdout_split(
        real_data, val_size, test_size, rng=rng)
    print(
        f"真实用户划分: train={len(train_real)}, val={len(val_real)}, test={len(test_real)}")

    # 只对训练集做增强，避免同源样本泄漏到验证/测试集
    synthetic = []
    for row in train_real:
        mbti = row["mbti"]
        n_variants = base_variants * type_weights.get(mbti, 1)
        for _ in range(n_variants):
            synthetic.append(augment_sample(row, feature_stats=feature_stats, rng=rng))

    print(f"合成样本: {len(synthetic)}")

    train_rows = train_real + synthetic
    combined = real_data + synthetic
    print(f"总计: {len(combined)}")

    # 保存增强后的数据集
    out_path = DATA_DIR / "dataset_augmented.csv"
    fieldnames = ["user_id", "source_user_id", "mbti"] + FEATURE_COLS
    write_csv(out_path, combined, fieldnames)
    print(f"已保存: {out_path}")

    split_dir = DATA_DIR / "split"
    split_dir.mkdir(exist_ok=True)
    for name, subset in [
        ("train", train_rows),
        ("val", val_real),
        ("test", test_real),
    ]:
        path = split_dir / f"{name}.csv"
        write_csv(path, subset, fieldnames)
        print(f"  {name}: {len(subset)}")

    manifest = {
        "real_samples": len(real_data),
        "synthetic_samples": len(synthetic),
        "ratio": f"1:{len(synthetic)/max(len(real_data),1):.1f}",
        "train_rows": len(train_rows),
        "val_rows": len(val_real),
        "test_rows": len(test_real),
        "base_variants": base_variants,
        "type_weights": type_weights,
        "train_real_users": [row["user_id"] for row in train_real],
        "val_real_users": [row["user_id"] for row in val_real],
        "test_real_users": [row["user_id"] for row in test_real],
    }
    (split_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  manifest: {split_dir / 'manifest.json'}")

    # 分布
    counts = Counter(row["mbti"] for row in combined)
    print(f"\nMBTI 分布:")
    for mbti, c in counts.most_common():
        print(f"  {mbti}: {c} ({c/len(combined)*100:.1f}%)")

    # 维度覆盖
    for idx, dim in enumerate(["IE", "NS", "FT", "JP"]):
        dim_counts = Counter(row["mbti"][idx] for row in combined)
        print(f"  {dim}: {dict(dim_counts)}")

    summarize_split("train", train_rows)
    summarize_split("val", val_real)
    summarize_split("test", test_real)


if __name__ == "__main__":
    main()
