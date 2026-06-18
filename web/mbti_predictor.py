"""
MBTI 混合预测器

结合 ML 模型预测和规则兜底，预测用户的 MBTI 类型。
- 模型可用且置信度高 → 使用模型
- 模型不可用或置信度低 → 使用规则兜底

用法:
    from web.mbti_predictor import predict_mbti
    result = predict_mbti(analysis)
"""

from mbti_features import (
    FEATURE_COLS,
    DIMENSION_LABELS,
    extract_features,
    merge_features,
)
import json
import pickle
import sys
from pathlib import Path

import numpy as np

# 将项目根目录加入 sys.path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


MODEL_DIR = Path(__file__).parent / "models"


# ── 规则兜底预测（基于 25 人种子数据校准）────────────────────

def _sigmoid(x: float, center: float, scale: float = 10) -> float:
    """将连续值映射到 [0, 1]，center 处 = 0.5。"""
    return 1.0 / (1.0 + 2.718281828 ** (-(x - center) * scale))


def rule_based_predict(features: dict) -> dict:
    """基于规则的 MBTI 预测，作为模型不可用时的兜底。

    阈值基于 25 人种子数据的实际分布校准。
    返回: {dimension: (letter, confidence)} 如 {"IE": ("I", 0.7), ...}
    """
    results = {}

    # ── I/E: 评论率 + 评论长度 ──
    # 种子数据: I 型 comment_rate 中位 ~0.03, E 型 ~0.81
    # 边界区: 0.3-0.5 (如 aada=INTJ 0.34, tjz230=INFP 0.54)
    cr = features.get("comment_rate", 0.3)
    acl = features.get("avg_comment_length", 30)
    # 评论率是主信号，评论长度是辅助（>60 字倾向 E/社交型表达）
    ie_score = _sigmoid(cr, 0.35, 8) * 0.7 + _sigmoid(acl, 50, 0.04) * 0.3
    if ie_score > 0.5:
        results["IE"] = ("E", round(
            min(0.5 + (ie_score - 0.5) * 0.6, 0.85), 2))
    else:
        results["IE"] = ("I", round(
            min(0.5 + (0.5 - ie_score) * 0.6, 0.85), 2))

    # ── N/S: 抽象度 (n_score) ──
    # 种子数据: N 型 n_score 中位 ~0.45, S 型 ~0.59
    # 但有大量重叠（0.4-0.65），置信度上限较低
    n_score = features.get("n_score", 0.5)
    ns_score = _sigmoid(n_score, 0.50, 12)
    if ns_score > 0.5:
        results["NS"] = ("S", round(
            min(0.5 + abs(ns_score - 0.5) * 0.5, 0.72), 2))
    else:
        results["NS"] = ("N", round(
            min(0.5 + abs(ns_score - 0.5) * 0.5, 0.72), 2))

    # ── F/T: 情感分数（归一化差值）──
    # f_score/t_score 是绝对计数，需归一化
    f_score = features.get("f_score", 0.5)
    t_score = features.get("t_score", 0.5)
    total_ft = f_score + t_score
    if total_ft > 1:
        # 有实际评论数据，用归一化差值
        ft_diff = (f_score - t_score) / total_ft
    else:
        # 无评论数据，用 lift 指标兜底
        f_lift = features.get("f_lift", 0)
        t_lift = features.get("t_lift", 0)
        total_lift = f_lift + t_lift
        ft_diff = (f_lift - t_lift) / total_lift if total_lift > 0 else 0
    ft_conf = _sigmoid(abs(ft_diff), 0.15, 10)
    if ft_diff > 0:
        results["FT"] = ("F", round(min(0.5 + ft_conf * 0.35, 0.85), 2))
    else:
        results["FT"] = ("T", round(min(0.5 + ft_conf * 0.35, 0.85), 2))

    # ── J/P: 想看比例 + 批量标记率 ──
    # 种子数据: J 型 wish_ratio 中位 ~0.07, P 型 ~0.49
    # 边界区: 0.2-0.4 (如 aada=INTJ 0.47, 174815909=INFP 0.45)
    wr = features.get("wish_ratio", 0.3)
    bp = features.get("bulk_pct", 0)
    # wish_ratio 是主信号: 低=J（看完才标）, 高=P（屯着想看）
    # bulk_pct 辅助: 极高(>50%) 倾向 J（有组织批量行为）
    jp_score = _sigmoid(wr, 0.25, 8) * 0.75 + \
        (1 - _sigmoid(bp, 30, 0.05)) * 0.25
    if jp_score > 0.5:
        results["JP"] = ("P", round(
            min(0.5 + (jp_score - 0.5) * 0.5, 0.80), 2))
    else:
        results["JP"] = ("J", round(
            min(0.5 + (0.5 - jp_score) * 0.5, 0.80), 2))

    return results


# ── ML 模型预测 ───────────────────────────────────────────────

_model = None
_scaler = None
_imputer_stats = None
_model_loaded = False


def _load_model():
    """加载模型（懒加载）。"""
    global _model, _scaler, _imputer_stats, _model_loaded
    if _model_loaded:
        return _model is not None

    model_path = MODEL_DIR / "mbti_model.pkl"
    scaler_path = MODEL_DIR / "scaler.pkl"

    if not model_path.exists() or not scaler_path.exists():
        _model_loaded = True
        return False

    try:
        with open(model_path, "rb") as f:
            _model = pickle.load(f)
        if isinstance(_model, dict):
            _imputer_stats = _model.get("imputer_statistics")
        if isinstance(_model, dict) and "models" in _model:
            _model = _model["models"]
        with open(scaler_path, "rb") as f:
            _scaler = pickle.load(f)
        _model_loaded = True
        return True
    except Exception:
        _model_loaded = True
        return False


def ml_predict(features: dict) -> dict | None:
    """使用 ML 模型预测 MBTI。

    返回: {dimension: (letter, confidence)} 或 None（模型不可用）
    """
    if not _load_model():
        return None

    try:
        # 构建特征向量
        row = []
        for col in FEATURE_COLS:
            val = features.get(col)
            if val is None:
                row.append(np.nan)
            else:
                row.append(val)
        vec = np.array([row], dtype=float)
        if _imputer_stats is not None:
            stats = np.array(_imputer_stats, dtype=float)
            nan_mask = np.isnan(vec)
            if nan_mask.any():
                vec[nan_mask] = np.take(stats, np.where(nan_mask)[1])
        else:
            vec = np.nan_to_num(vec, nan=0.0)
        vec_scaled = _scaler.transform(vec)

        results = {}
        for dim, clf in _model.items():
            if dim not in DIMENSION_LABELS:
                continue
            prob = clf.predict_proba(vec_scaled)[0]
            pred_class = int(np.argmax(prob))
            confidence = float(prob[pred_class])
            letter = DIMENSION_LABELS[dim][pred_class]
            results[dim] = (letter, confidence)

        return results
    except Exception:
        return None


# ── 混合预测 ──────────────────────────────────────────────────

def predict_mbti(analysis: dict) -> dict:
    """预测用户 MBTI 类型。

    参数:
        analysis: full_analysis() 返回的分析结果

    返回:
        {
            "mbti": "INTJ",
            "confidence": 0.75,
            "dimensions": {
                "IE": {"letter": "I", "confidence": 0.8},
                "NS": {"letter": "N", "confidence": 0.7},
                "FT": {"letter": "T", "confidence": 0.75},
                "JP": {"letter": "J", "confidence": 0.7},
            },
            "method": "ml+rules" | "rules_only"
        }
    """
    # 提取特征（优先电影，书籍补充）
    movie_features = extract_features(analysis, "movie")
    book_features = extract_features(analysis, "book")
    features = merge_features(movie_features, book_features)

    if not features:
        return {
            "mbti": None,
            "confidence": 0,
            "dimensions": {},
            "method": "insufficient_data",
        }

    # 规则预测（始终可用）
    rule_results = rule_based_predict(features)

    # 尝试 ML 模型
    ml_results = ml_predict(features)

    # 混合策略
    # 模型置信度 >= 0.6 → 信任模型
    # 模型规则一致 → 取均值
    # 其他 → 回退规则
    CONF_THRESHOLD = 0.6
    dimensions = {}
    method = "rules_only"

    if ml_results:
        method = "ml+rules"
        for dim in DIMENSION_LABELS:
            ml_r = ml_results.get(dim)
            rule_r = rule_results.get(dim)

            if ml_r and ml_r[1] >= CONF_THRESHOLD:
                # 模型置信度高，使用模型
                dimensions[dim] = {"letter": ml_r[0],
                                   "confidence": round(ml_r[1], 2)}
            elif ml_r and rule_r and ml_r[0] == rule_r[0]:
                # 模型和规则一致
                dimensions[dim] = {"letter": ml_r[0],
                                   "confidence": round((ml_r[1] + rule_r[1]) / 2, 2)}
            elif rule_r:
                # 模型置信度低，使用规则
                dimensions[dim] = {"letter": rule_r[0],
                                   "confidence": round(rule_r[1], 2)}
            else:
                dimensions[dim] = {"letter": "X", "confidence": 0}
    else:
        for dim in DIMENSION_LABELS:
            r = rule_results.get(dim, ("X", 0))
            dimensions[dim] = {"letter": r[0], "confidence": round(r[1], 2)}

    # 组合 MBTI 字符串
    mbti_str = "".join(dimensions[d]["letter"]
                       for d in ["IE", "NS", "FT", "JP"])
    overall_conf = np.mean([dimensions[d]["confidence"] for d in dimensions])

    return {
        "mbti": mbti_str,
        "confidence": round(float(overall_conf), 2),
        "dimensions": dimensions,
        "method": method,
    }
