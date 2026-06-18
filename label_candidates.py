"""
为未标注候选用户分配 MBTI 标签。

基于 analysis JSON 中的多维行为特征，为候选用户分配 MBTI 标签，
并追加到 seeds.json 中。

特征来源:
- I/E: 评论率 + 平均评论长度 (外倾/内倾表达度)
- N/S: 抽象度 n_score + 时代偏好 + 类型多样性
- F/T: 评论情感 f_score vs t_score
- J/P: wish_ratio (未消费欲望) + bulk_pct (组织性)

用法:
    python label_candidates.py              # 标注并追加到 seeds.json
    python label_candidates.py --dry-run    # 预览标注结果，不写文件
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULT_DIR = ROOT / "result"
SEEDS_PATH = ROOT / "data" / "mbti_training" / "seeds.json"
CANDIDATES_PATH = ROOT / "data" / "mbti_training" / "unlabeled_candidates.json"


# ── 手工标注清单 ──────────────────────────────────────────────
# 每个用户的 MBTI 标签基于以下证据综合判断:
#
# I/E 维度:
#   comment_rate > 0.7 且 avg_comment_length > 50 → E 倾向
#   comment_rate < 0.3 或 avg_comment_length < 30 → I 倾向
#
# N/S 维度:
#   n_score < 0.45 → S (偏好写实、经典、具象作品)
#   n_score > 0.6  → N (偏好实验、抽象、概念化作品)
#   0.45 ~ 0.6    → 边界，需结合其他维度
#
# F/T 维度:
#   comment_sentiment.f_score >> t_score → F (被人性情感打动)
#   comment_sentiment.t_score >> f_score → T (被系统概念吸引)
#
# J/P 维度:
#   wish_ratio > 0.5 且 bulk_pct < 15 → P (大量收藏但少消费，随性)
#   wish_ratio < 0.2 或 bulk_pct > 25 → J (已消费比例高，有组织性)

MANUAL_LABELS: dict[str, str] = {
    # ns_low group — 对填补 S 类空白至关重要
    # T-leaning(1073F/1852T), 极低n=0.283, 高comment_rate=0.8
    "cabaret":          "ESTJ",
    "zionius":          "INTJ",  # 极低comment_rate=0.023, 哲学用户名, 经典偏好, n=0.427
    # ns_boundary group — N/S 边界样本
    # 极高comment_rate=0.997, 书影双修(1186+2550), balanced F/T
    "shunian":          "ENFJ",
    "4075628":          "ISTJ",  # 纯书虫(2155书), T-leaning(29F/37T), 极低wish
    "tjz230":           "INFP",  # F-leaning(2256F/979T), 极高wish(1379), 22演化阶段
    "feizhaizhangmen":  "ISFJ",  # F-leaning(128F/66T), 短评论(25字), 务实风格, n=0.589
    "fangyunan":        "ISFP",  # 纯书虫(1170), 无评论数据, 701想看(P行为), n=0.558
    # ns_high group — N 类样本补充
    "xilouchen":        "INFP",  # 极强F(6152F/1183T), 长评论(91字), 严格评分(avg2.62)
    "Sacronlau":        "INFJ",  # F-leaning(2602F/1901T), 深度长评(110字), 极低wish
    # 纯书虫(1390), 2300想读(P行为), 高评分(avg4.1), 长评(135字)
    "1087580":          "ENFP",
    "102454210":        "INFJ",  # F-leaning(635F/460T), 长评(121字), 大量想看
    "156883939":        "ENFP",  # 强F(408F/230T), 极高评分(avg4.49, 59%五星), 2659想读
    # balanced(995F/909T), 高wish(1396), 经典偏好(era2012)
    "171133816":        "ISFP",
    "film101":          "ISTJ",  # balanced(44F/49T), 短评论标签式(22字), 万部系统性
    "aada":             "INTJ",  # F-leaning(43F/18T), 严格评分, 16年跨度, 少评论
    # low_volume group — 数据量不足
    # wzfeng2019 排除: 仅 9 部电影 + 14 本书, 全五星, 不具代表性
    "Schopenhauer126":  "INTJ",  # T-leaning(0F/4T), 哲学用户名, 严格评分, n=0.646
}


def load_existing_seeds() -> list[dict]:
    """加载现有 seeds.json。"""
    if not SEEDS_PATH.exists():
        return []
    return json.loads(SEEDS_PATH.read_text(encoding="utf-8"))


def load_candidate_features() -> dict[str, dict]:
    """加载候选用户特征。"""
    if not CANDIDATES_PATH.exists():
        return {}
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    return {c["user_id"]: c for c in candidates}


def validate_labels(labels: dict[str, str]) -> list[str]:
    """验证 MBTI 标签格式。"""
    errors = []
    valid_ie = {"I", "E"}
    valid_ns = {"N", "S"}
    valid_ft = {"F", "T"}
    valid_jp = {"J", "P"}
    for uid, mbti in labels.items():
        if len(mbti) != 4:
            errors.append(f"{uid}: {mbti} 长度不为 4")
            continue
        if mbti[0] not in valid_ie:
            errors.append(f"{uid}: {mbti} 第 1 位 {mbti[0]} 不在 IE")
        if mbti[1] not in valid_ns:
            errors.append(f"{uid}: {mbti} 第 2 位 {mbti[1]} 不在 NS")
        if mbti[2] not in valid_ft:
            errors.append(f"{uid}: {mbti} 第 3 位 {mbti[2]} 不在 FT")
        if mbti[3] not in valid_jp:
            errors.append(f"{uid}: {mbti} 第 4 位 {mbti[3]} 不在 JP")
    return errors


def print_distribution(labels: dict[str, str]):
    """打印维度分布。"""
    from collections import Counter

    total = len(labels)
    print(f"\n总计: {total} 个用户\n")

    # MBTI 类型分布
    type_counts = Counter(labels.values())
    print("MBTI 类型分布:")
    for mbti, count in type_counts.most_common():
        print(f"  {mbti}: {count} ({count/total*100:.1f}%)")

    # 维度分布
    for idx, dim in enumerate(["IE", "NS", "FT", "JP"]):
        counts = Counter(mbti[idx] for mbti in labels.values())
        print(f"\n{dim} 维度:")
        for letter, count in sorted(counts.items()):
            print(f"  {letter}: {count} ({count/total*100:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="MBTI 候选用户标注")
    parser.add_argument("--dry-run", action="store_true", help="预览标注结果，不写文件")
    args = parser.parse_args()

    # 验证标签
    errors = validate_labels(MANUAL_LABELS)
    if errors:
        print("标签验证错误:")
        for err in errors:
            print(f"  {err}")
        sys.exit(1)

    # 加载现有种子
    existing_seeds = load_existing_seeds()
    existing_ids = {s["user_id"] for s in existing_seeds}
    print(f"现有种子: {len(existing_seeds)} 个")

    # 加载候选特征
    candidates = load_candidate_features()
    print(f"候选用户: {len(candidates)} 个")

    # 构建新种子条目
    new_seeds = []
    skipped = []
    for uid, mbti in MANUAL_LABELS.items():
        if uid in existing_ids:
            skipped.append(uid)
            continue

        feature = candidates.get(uid, {})
        new_seeds.append({
            "user_id": uid,
            "source_user_id": feature.get("source_user_id", uid),
            "mbti": mbti,
            "source": "manual_behavioral_labeling",
            "confidence": "behavioral_inference",
            "discovered_at": datetime.now().strftime("%Y-%m-%d"),
            "labeling_evidence": {
                "n_score": feature.get("n_score"),
                "comment_rate": feature.get("comment_rate"),
                "avg_comment_length": feature.get("avg_comment_length"),
                "wish_ratio": feature.get("wish_ratio"),
                "bulk_pct": feature.get("bulk_pct"),
                "total_collected": feature.get("total_collected"),
                "priority_group": feature.get("priority_group"),
            },
        })

    if skipped:
        print(f"\n跳过已存在: {skipped}")

    # 合并
    all_seeds = existing_seeds + new_seeds

    # 合并后的完整标签分布
    all_labels = {s["user_id"]: s["mbti"] for s in all_seeds}
    print_distribution(all_labels)

    if args.dry_run:
        print("\n[DRY RUN] 不写文件")
        print(f"\n将新增 {len(new_seeds)} 个种子:")
        for seed in new_seeds:
            print(f"  {seed['user_id']}: {seed['mbti']} "
                  f"(n={seed['labeling_evidence'].get('n_score', '?')}, "
                  f"cr={seed['labeling_evidence'].get('comment_rate', '?')}, "
                  f"wr={seed['labeling_evidence'].get('wish_ratio', '?')})")
    else:
        SEEDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEEDS_PATH.write_text(
            json.dumps(all_seeds, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n已保存 {len(all_seeds)} 个种子到: {SEEDS_PATH}")
        print(f"新增 {len(new_seeds)} 个")


if __name__ == "__main__":
    main()
