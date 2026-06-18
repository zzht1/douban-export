"""
MBTI 特征提取公共模块

被以下模块引用:
- build_mbti_dataset.py   (训练数据集构建)
- web/mbti_predictor.py   (推理预测)
- build_mbti_candidate_pool.py (候选池生成)

所有 MBTI 相关的特征列名、提取逻辑和合并逻辑统一在此维护。
"""

import math
from typing import Optional

FEATURE_COLS = [
    "comment_rate",
    "avg_comment_length",
    "n_score",
    "era_median_year",
    "genre_diversity",
    "f_score",
    "t_score",
    "f_lift",
    "t_lift",
    "f_pct_top_rated",
    "t_pct_top_rated",
    "wish_ratio",
    "bulk_pct",
    "rating_std",
    "avg_rating",
    "total_collected",
    "five_star_pct",
]

# MBTI 维度标签
DIMENSIONS = ["IE", "NS", "FT", "JP"]
DIMENSION_LABELS = {
    "IE": ("I", "E"),  # 0=I, 1=E
    "NS": ("N", "S"),  # 0=N, 1=S
    "FT": ("F", "T"),  # 0=F, 1=T
    "JP": ("J", "P"),  # 0=J, 1=P
}


def extract_features(analysis: dict, dtype: str = "movie") -> Optional[dict]:
    """从 full_analysis 结果中提取特征向量。

    Parameters:
        analysis: analyzer.full_analysis() 的返回值
        dtype: 数据类别 "movie" / "book" / "music"

    Returns:
        特征字典，或 None（无可用数据时）
    """
    section = analysis.get(dtype, {})
    if not section or not section.get("collected_count"):
        return None

    collected = section.get("collected_count", 0)
    features: dict[str, float | int] = {}

    # ── 评论行为 ──
    samples = section.get("samples", [])
    commented = [s for s in samples if s.get("comment")]
    features["comment_rate"] = len(commented) / max(len(samples), 1)
    features["avg_comment_length"] = (
        sum(len(s["comment"]) for s in commented) / len(commented)
        if commented else 0
    )

    # ── N/S: 抽象度 ──
    abstraction = section.get("abstraction_index", {})
    features["n_score"] = abstraction.get("n_score", 0.5)

    # ── N/S: 时代中位年 ──
    era = section.get("era_orientation", {})
    features["era_median_year"] = era.get("median_release_year", 2010)

    # ── N/S: 类型多样性 (Shannon 熵) ──
    genre_breakdown = section.get("genre_breakdown", {})
    total_genre = sum(genre_breakdown.values())
    if total_genre > 0:
        entropy = 0.0
        for count in genre_breakdown.values():
            p = count / total_genre
            if p > 0:
                entropy -= p * math.log2(p)
        features["genre_diversity"] = entropy
    else:
        features["genre_diversity"] = 0

    # ── F/T: 评论情感 ──
    sentiment = section.get("comment_sentiment", {})
    features["f_score"] = sentiment.get("f_score", 0.5)
    features["t_score"] = sentiment.get("t_score", 0.5)

    # ── F/T: 5星类型偏好 ──
    top_rated = section.get("top_rated_genre_bias", {})
    features["f_lift"] = top_rated.get("f_lift", 0)
    features["t_lift"] = top_rated.get("t_lift", 0)
    features["f_pct_top_rated"] = top_rated.get("f_pct_top_rated", 0.5)
    features["t_pct_top_rated"] = top_rated.get("t_pct_top_rated", 0.5)

    # ── J/P: 想看比例 ──
    wish_count = section.get("wish_count", 0)
    features["wish_ratio"] = wish_count / max(collected + wish_count, 1)

    # ── J/P: 批量标记率 ──
    bulk_marking = section.get("bulk_marking", {})
    features["bulk_pct"] = bulk_marking.get("bulk_pct", 0)

    # ── 评分分布 ──
    rating_distribution = section.get("rating_distribution", {})
    ratings: list[int] = []
    for star, count in rating_distribution.items():
        if str(star).isdigit():
            ratings.extend([int(star)] * count)
    if ratings:
        mean = sum(ratings) / len(ratings)
        variance = sum((r - mean) ** 2 for r in ratings) / len(ratings)
        features["rating_std"] = variance ** 0.5
    else:
        features["rating_std"] = 0

    features["avg_rating"] = section.get("avg_rating", 0)
    features["total_collected"] = collected
    features["five_star_pct"] = rating_distribution.get(
        "5", 0) / max(collected, 1)

    return features


def merge_features(
    movie_features: Optional[dict],
    book_features: Optional[dict],
) -> Optional[dict]:
    """合并电影和书籍特征向量。

    策略:
    - 仅有电影或书籍时，直接使用
    - 两者都有时，对同一特征取均值
    """
    if not movie_features and not book_features:
        return None
    if not movie_features:
        return dict(book_features)
    if not book_features:
        return dict(movie_features)

    merged = dict(movie_features)
    for key in FEATURE_COLS:
        mv = movie_features.get(key)
        bv = book_features.get(key)
        if mv is not None and bv is not None:
            merged[key] = (mv + bv) / 2
        elif bv is not None:
            merged[key] = bv
    return merged


def check_quality(
    features: Optional[dict],
    min_items: int = 30,
) -> tuple[bool, str]:
    """检查特征是否满足最低质量要求。"""
    if features is None:
        return False, "无数据"
    if features.get("total_collected", 0) < min_items:
        return False, f"标记量不足 ({features['total_collected']} < {min_items})"
    return True, "OK"
