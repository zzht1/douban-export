"""
生成模拟 MBTI 训练数据，用于验证训练流程。

用法: python generate_mock_data.py
"""

import csv
import random
from pathlib import Path

import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "mbti_training"
FEATURE_COLS = [
    "comment_rate", "avg_comment_length", "n_score", "era_median_year",
    "genre_diversity", "f_score", "t_score", "f_lift", "t_lift",
    "f_pct_top_rated", "t_pct_top_rated", "wish_ratio", "bulk_pct",
    "rating_std", "avg_rating", "total_collected", "five_star_pct",
]

# MBTI 类型分布（模拟真实分布，I/F/N/J 偏多）
MBTI_DISTRIBUTION = {
    "INFJ": 0.15, "INFP": 0.14, "INTJ": 0.08, "INTP": 0.07,
    "ISFJ": 0.06, "ISFP": 0.05, "ISTJ": 0.04, "ISTP": 0.03,
    "ENFJ": 0.08, "ENFP": 0.09, "ENTJ": 0.05, "ENTP": 0.05,
    "ESFJ": 0.04, "ESFP": 0.03, "ESTJ": 0.02, "ESTP": 0.02,
}

# 每个维度的特征偏移（用于模拟不同 MBTI 的特征差异）
DIM_BIAS = {
    # I vs E: 评论率、评论长度
    "I": {"comment_rate": 0.3, "avg_comment_length": 40},
    "E": {"comment_rate": 0.6, "avg_comment_length": 25},
    # N vs S: 抽象度、时代年份、类型多样性
    "N": {"n_score": 0.7, "era_median_year": 2005, "genre_diversity": 3.5},
    "S": {"n_score": 0.3, "era_median_year": 2015, "genre_diversity": 2.5},
    # F vs T: 情感分、类型偏好
    "F": {"f_score": 0.7, "t_score": 0.3, "f_lift": 0.3, "t_lift": -0.1,
          "f_pct_top_rated": 0.65, "t_pct_top_rated": 0.35},
    "T": {"f_score": 0.3, "t_score": 0.6, "f_lift": -0.1, "t_lift": 0.3,
          "f_pct_top_rated": 0.40, "t_pct_top_rated": 0.60},
    # J vs P: 想看比例、批量标记率、评分标准差
    "J": {"wish_ratio": 0.4, "bulk_pct": 0.15, "rating_std": 0.8},
    "P": {"wish_ratio": 0.7, "bulk_pct": 0.05, "rating_std": 1.2},
}


def generate_features(mbti: str) -> dict:
    """根据 MBTI 类型生成带有偏移的特征。"""
    features = {}

    # 基础值
    base = {
        "comment_rate": 0.4,
        "avg_comment_length": 30,
        "n_score": 0.5,
        "era_median_year": 2010,
        "genre_diversity": 3.0,
        "f_score": 0.5,
        "t_score": 0.5,
        "f_lift": 0.0,
        "t_lift": 0.0,
        "f_pct_top_rated": 0.5,
        "t_pct_top_rated": 0.5,
        "wish_ratio": 0.5,
        "bulk_pct": 0.1,
        "rating_std": 1.0,
        "avg_rating": 3.8,
        "total_collected": random.randint(30, 500),
        "five_star_pct": random.uniform(0.1, 0.4),
    }

    # 应用每个维度的偏移
    for letter in mbti:
        for key, offset in DIM_BIAS[letter].items():
            if key in base:
                base[key] = offset + random.uniform(-0.15, 0.15)

    # 确保值在合理范围内
    for key in FEATURE_COLS:
        if key == "total_collected":
            features[key] = int(base[key])
        elif key == "era_median_year":
            features[key] = int(base[key])
        elif key in ("comment_rate", "n_score", "f_pct_top_rated", "t_pct_top_rated",
                     "wish_ratio", "bulk_pct", "five_star_pct"):
            features[key] = max(0.0, min(1.0, base[key]))
        elif key == "avg_comment_length":
            features[key] = max(0, base[key])
        else:
            features[key] = base[key]

    return features


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 根据分布生成用户
    users = []
    n_users = 80

    # 按比例分配每种类型的数量
    for mbti, ratio in MBTI_DISTRIBUTION.items():
        count = max(1, int(n_users * ratio))
        for _ in range(count):
            features = generate_features(mbti)
            users.append({"user_id": f"mock_{len(users):04d}",
                         "mbti": mbti, **features})

    random.shuffle(users)

    # 拆分为 train/val/test
    n = len(users)
    train_end = int(n * 0.8)
    val_end = train_end + int(n * 0.1)

    splits = [
        ("dataset", users),
        ("split/train", users[:train_end]),
        ("split/val", users[train_end:val_end]),
        ("split/test", users[val_end:]),
    ]

    for name, data in splits:
        path = OUTPUT_DIR / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=["user_id", "mbti"] + FEATURE_COLS)
            writer.writeheader()
            for row in data:
                writer.writerow(row)
        print(f"已保存: {path} ({len(data)} 条)")

    # 统计
    from collections import Counter
    counts = Counter(u["mbti"] for u in users)
    print(f"\n总计: {len(users)} 条模拟数据")
    print("MBTI 分布:")
    for mbti, count in sorted(counts.items()):
        print(f"  {mbti}: {count}")


if __name__ == "__main__":
    main()
