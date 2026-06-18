"""
MBTI 预测器批量测试

对 result/ 目录下所有已知标签用户运行预测，与真实标签对比，
输出维度准确率和详细预测对比表。
"""

from mbti_features import extract_features, merge_features
from web.mbti_predictor import predict_mbti, rule_based_predict, ml_predict
from mbti_features import DIMENSIONS, DIMENSION_LABELS
import json
import sys
import io
from pathlib import Path

# Windows GBK stdout fix
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding='utf-8', errors='replace')

# 项目根目录
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def load_seeds() -> dict[str, str]:
    """从 seeds.json 加载已知标签。"""
    seeds_path = ROOT / "data" / "mbti_training" / "seeds.json"
    if not seeds_path.exists():
        return {}
    seeds = json.loads(seeds_path.read_text(encoding="utf-8"))
    return {s["user_id"]: s["mbti"].upper() for s in seeds}


def find_analysis_json(uid: str) -> Path | None:
    """查找用户的 analysis JSON 文件。"""
    candidates = [
        ROOT / "result" / f"{uid}_analysis.json",
        ROOT / "data" / uid / f"{uid}_analysis.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def letter_accuracy(
    predictions: list[tuple[str, str]],
    dim_idx: int,
) -> float | None:
    """计算某个维度的字母准确率。"""
    correct = 0
    total = 0
    for true_mbti, pred_mbti in predictions:
        if len(true_mbti) == 4 and len(pred_mbti) >= 4:
            total += 1
            if true_mbti[dim_idx] == pred_mbti[dim_idx]:
                correct += 1
    return correct / total if total > 0 else None


def main():
    seeds = load_seeds()
    if not seeds:
        print("No seeds found. Run label_candidates.py first.")
        return

    print(f"已知标签用户: {len(seeds)} 人")
    print("=" * 90)
    print(f"{'User':<20} {'True':>6} {'Pred':>6} {'Method':<12} "
          f"{'IE':>4} {'NS':>4} {'FT':>4} {'JP':>4} {'Conf':>6}")
    print("-" * 90)

    results: list[tuple[str, str, dict]] = []  # (uid, true_mbti, detail)
    predictions: list[tuple[str, str]] = []  # (true_mbti, pred_mbti)
    tested = 0
    skipped = 0

    for uid, true_mbti in sorted(seeds.items()):
        analysis_path = find_analysis_json(uid)
        if not analysis_path:
            print(f"{uid:<20} {true_mbti:>6}  (no analysis JSON)")
            skipped += 1
            continue

        with open(analysis_path, encoding="utf-8") as f:
            analysis = json.load(f)

        pred = predict_mbti(analysis)
        pred_mbti = pred.get("mbti") or "????"
        method = pred.get("method", "?")
        conf = pred.get("confidence", 0)
        dims = pred.get("dimensions", {})

        # 维度对比
        dim_strs = []
        for i, dim in enumerate(DIMENSIONS):
            if len(true_mbti) > i and len(pred_mbti) > i:
                match = "v" if true_mbti[i] == pred_mbti[i] else "x"
            else:
                match = "?"
            dim_strs.append(
                f"{pred_mbti[i] if i < len(pred_mbti) else '?'}{match}")

        print(f"{uid:<20} {true_mbti:>6} {pred_mbti:>6} {method:<12} "
              f"{dim_strs[0]:>4} {dim_strs[1]:>4} {dim_strs[2]:>4} {dim_strs[3]:>4} "
              f"{conf:>6.2f}")

        results.append((uid, true_mbti, pred))
        predictions.append((true_mbti, pred_mbti))
        tested += 1

    # ── 汇总统计 ──
    print("\n" + "=" * 90)
    print(f"测试完成: {tested} 人预测, {skipped} 人跳过")

    if predictions:
        print("\n── 维度准确率 ──")
        for i, dim in enumerate(DIMENSIONS):
            acc = letter_accuracy(predictions, i)
            if acc is not None:
                bar = "#" * int(acc * 20) + "." * (20 - int(acc * 20))
                print(f"  {dim}: {acc:.1%} {bar}")
            else:
                print(f"  {dim}: N/A")

        # 全类型准确率
        full_correct = sum(1 for t, p in predictions if t == p)
        print(f"\n  全类型匹配: {full_correct}/{len(predictions)} "
              f"({full_correct / len(predictions):.1%})")

        # 至少 3 维度正确
        three_plus = 0
        for t, p in predictions:
            if len(t) == 4 and len(p) >= 4:
                correct_dims = sum(1 for i in range(4) if t[i] == p[i])
                if correct_dims >= 3:
                    three_plus += 1
        print(f"  ≥3 维度正确: {three_plus}/{len(predictions)} "
              f"({three_plus / len(predictions):.1%})")

    # ── 置信度分层准确率 ──
    if predictions and results:
        print("\n── 置信度分层准确率 ──")
        high_conf = [(t, d.get("mbti", "????")) for (uid, t, d) in results
                     if d.get("confidence", 0) >= 0.7]
        med_conf = [(t, d.get("mbti", "????")) for (uid, t, d) in results
                    if 0.5 <= d.get("confidence", 0) < 0.7]
        low_conf = [(t, d.get("mbti", "????")) for (uid, t, d) in results
                    if d.get("confidence", 0) < 0.5]

        for label, subset in [("高(≥0.7)", high_conf), ("中(0.5-0.7)", med_conf), ("低(<0.5)", low_conf)]:
            if not subset:
                print(f"  {label}: N/A (0 人)")
                continue
            correct = sum(1 for t, p in subset if t == p)
            three_plus = sum(1 for t, p in subset if sum(1 for i in range(4) if t[i] == p[i]) >= 3)
            print(f"  {label}: {len(subset)} 人 | 全匹配 {correct}/{len(subset)} ({correct/len(subset):.0%}) | ≥3维 {three_plus}/{len(subset)} ({three_plus/len(subset):.0%})")

    # ── 纯规则 vs 混合对比 ──
    print("\n── 规则兜底单独准确率（仅参考）──")
    rule_predictions: list[tuple[str, str]] = []
    for uid, true_mbti, detail in results:
        analysis_path = find_analysis_json(uid)
        if not analysis_path:
            continue
        with open(analysis_path, encoding="utf-8") as f:
            analysis = json.load(f)
        movie_features = extract_features(analysis, "movie")
        book_features = extract_features(analysis, "book")
        features = merge_features(movie_features, book_features)
        if not features:
            continue
        rule_result = rule_based_predict(features)
        rule_mbti = "".join(rule_result[d][0] for d in DIMENSIONS)
        rule_predictions.append((true_mbti, rule_mbti))

    if rule_predictions:
        for i, dim in enumerate(DIMENSIONS):
            acc = letter_accuracy(rule_predictions, i)
            if acc is not None:
                print(f"  {dim}: {acc:.1%}")

    # ── ML 模型可用性检查 ──
    print("\n── 模型状态 ──")
    ml_features = None
    for uid, true_mbti, detail in results[:1]:
        analysis_path = find_analysis_json(uid)
        if analysis_path:
            with open(analysis_path, encoding="utf-8") as f:
                analysis = json.load(f)
            movie_features = extract_features(analysis, "movie")
            book_features = extract_features(analysis, "book")
            ml_features = merge_features(movie_features, book_features)

    if ml_features:
        ml_result = ml_predict(ml_features)
        if ml_result:
            print(f"  ML 模型: 可用 ({len(ml_result)} 维度)")
        else:
            print("  ML 模型: 不可用 (仅使用规则兜底)")
    else:
        print("  ML 模型: 无法测试")


if __name__ == "__main__":
    main()
