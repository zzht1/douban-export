"""
横向对比所有用户的分析 JSON，提取可用于 MBTI 维度设计的特征。
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "result"

USERS = [
    "156883939", "feizhaizhangmen", "aada", "4075628", "wzfeng2019",
    "171133816", "xilouchen", "102454210", "film101", "Sacronlau",
    "cabaret", "tjz230", "fangyunan", "Schopenhauer126", "1087580",
    "shunian", "zionius",
]


def safe_get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d


def extract_features(uid):
    path = DATA_DIR / f"{uid}_analysis.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    movie = data.get("movie", {})
    book = data.get("book", {})
    cross = data.get("cross_media", {})

    feat = {"user_id": uid}

    # --- 基础量 ---
    feat["movie_count"] = safe_get(movie, "collected_count", default=0)
    feat["book_count"] = safe_get(book, "collected_count", default=0)
    feat["movie_wish"] = safe_get(movie, "wish_count", default=0)
    feat["book_wish"] = safe_get(book, "wish_count", default=0)
    feat["total_collected"] = feat["movie_count"] + feat["book_count"]

    # 书影比例
    if feat["total_collected"] > 0:
        feat["book_ratio"] = feat["book_count"] / feat["total_collected"]
    else:
        feat["book_ratio"] = 0

    # 想看/想读 vs 已标记 → 行动力指标
    total_action = feat["movie_count"] + feat["movie_wish"] + \
        feat["book_count"] + feat["book_wish"]
    total_wish = feat["movie_wish"] + feat["book_wish"]
    feat["wish_ratio"] = total_wish / total_action if total_action > 0 else 0

    # --- 评分分布 ---
    for label, d in [("movie", movie), ("book", book)]:
        rd = safe_get(d, "rating_distribution", default={})
        feat[f"{label}_avg"] = safe_get(d, "avg_rating", default=0)
        # 评分集中度（高分占比）
        total_rated = sum(rd.values()) if rd else 0
        high = sum(rd.get(str(s), 0) for s in [4, 5]) if rd else 0
        low = sum(rd.get(str(s), 0) for s in [1, 2]) if rd else 0
        feat[f"{label}_high_pct"] = high / \
            total_rated if total_rated > 0 else 0
        feat[f"{label}_low_pct"] = low / total_rated if total_rated > 0 else 0
        # 打分条数
        feat[f"{label}_rated_count"] = total_rated
        # 5星占比
        feat[f"{label}_5star_pct"] = rd.get(
            "5", 0) / total_rated if total_rated > 0 else 0

    # --- 类型广度（genre_breakdown）---
    for label, d in [("movie", movie), ("book", book)]:
        genres = safe_get(d, "genre_breakdown", default={})
        feat[f"{label}_genre_count"] = len(genres)
        if genres:
            sorted_g = sorted(genres.items(), key=lambda x: -x[1])
            top3_total = sum(v for _, v in sorted_g[:3])
            all_total = sum(genres.values())
            # top3 集中度
            feat[f"{label}_top3_genre_pct"] = top3_total / \
                all_total if all_total > 0 else 0
            feat[f"{label}_top_genre"] = sorted_g[0][0] if sorted_g else ""
        else:
            feat[f"{label}_top3_genre_pct"] = 0
            feat[f"{label}_top_genre"] = ""

    # --- 国别分布 ---
    for label, d in [("movie", movie), ("book", book)]:
        countries = safe_get(d, "country_breakdown", default={})
        feat[f"{label}_country_count"] = len(countries)
        if countries:
            sorted_c = sorted(countries.items(), key=lambda x: -x[1])
            top1_total = sorted_c[0][1]
            all_total = sum(countries.values())
            feat[f"{label}_top1_country_pct"] = top1_total / \
                all_total if all_total > 0 else 0
            feat[f"{label}_top_country"] = sorted_c[0][0]
        else:
            feat[f"{label}_top1_country_pct"] = 0
            feat[f"{label}_top_country"] = ""

    # --- 评论风格（samples） ---
    for label, d in [("movie", movie), ("book", book)]:
        samples = safe_get(d, "samples", default=[])
        if samples:
            # 有评论的比例
            with_comment = [s for s in samples if s.get("comment")]
            feat[f"{label}_comment_pct"] = len(with_comment) / len(samples)
            # 平均评论长度
            comment_lens = [len(s["comment"]) for s in with_comment]
            feat[f"{label}_avg_comment_len"] = sum(
                comment_lens) / len(comment_lens) if comment_lens else 0
        else:
            feat[f"{label}_comment_pct"] = 0
            feat[f"{label}_avg_comment_len"] = 0

    # --- 时间节奏 ---
    for label, d in [("movie", movie), ("book", book)]:
        dow = safe_get(d, "day_of_week_rhythm", default={})
        if dow:
            # 周末vs工作日
            weekday = sum(dow.get(str(i), 0) for i in range(5))
            weekend = sum(dow.get(str(i), 0) for i in [5, 6])
            total_dw = weekday + weekend
            feat[f"{label}_weekend_pct"] = weekend / \
                total_dw if total_dw > 0 else 0
        else:
            feat[f"{label}_weekend_pct"] = 0

    # --- 品味演化 ---
    for label, d in [("movie", movie), ("book", book)]:
        evo = safe_get(d, "taste_evolution", default=[])
        feat[f"{label}_evo_phases"] = len(evo) if evo else 0

    # --- 跨媒体 ---
    feat["cross_overlaps"] = len(safe_get(cross, "title_overlaps", default=[]))

    # --- hidden_patterns 数量 ---
    for label, d in [("movie", movie), ("book", book)]:
        hp = safe_get(d, "hidden_patterns", default=[])
        feat[f"{label}_hidden_count"] = len(hp) if hp else 0

    # --- 年度跨度 ---
    for label, d in [("movie", movie), ("book", book)]:
        yearly = safe_get(d, "yearly_breakdown", default={})
        if yearly:
            years = [int(y) for y in yearly.keys() if y.isdigit()]
            feat[f"{label}_year_span"] = max(
                years) - min(years) if len(years) >= 2 else 0
            feat[f"{label}_active_years"] = len(years)
        else:
            feat[f"{label}_year_span"] = 0
            feat[f"{label}_active_years"] = 0

    # --- F/T 维度：评论语义 ---
    for label, d in [("movie", movie), ("book", book)]:
        cs = safe_get(d, "comment_sentiment", default={})
        feat[f"{label}_f_score"] = cs.get("f_score", 0)
        feat[f"{label}_t_score"] = cs.get("t_score", 0)
        feat[f"{label}_f_ratio"] = cs.get("f_ratio", 0.5)
        feat[f"{label}_t_ratio"] = cs.get("t_ratio", 0.5)
        feat[f"{label}_ft_leaning"] = cs.get("leaning", "unknown")
        feat[f"{label}_ft_comments"] = cs.get("comment_count", 0)

    # --- F/T 维度：top_rated 类型偏好 ---
    for label, d in [("movie", movie), ("book", book)]:
        gb = safe_get(d, "top_rated_genre_bias", default={})
        feat[f"{label}_genre_f_pct"] = gb.get("f_pct_top_rated", 0)
        feat[f"{label}_genre_t_pct"] = gb.get("t_pct_top_rated", 0)
        feat[f"{label}_genre_bias"] = gb.get("bias", "unknown")
        feat[f"{label}_genre_f_lift"] = gb.get("f_lift", 0)
        feat[f"{label}_genre_t_lift"] = gb.get("t_lift", 0)

    # --- N/S 维度：抽象度 ---
    for label, d in [("movie", movie), ("book", book)]:
        ai = safe_get(d, "abstraction_index", default={})
        feat[f"{label}_n_score"] = ai.get("n_score", 0)
        feat[f"{label}_ns_leaning"] = ai.get("leaning", "unknown")
        feat[f"{label}_cultural_breadth"] = ai.get("cultural_breadth", 0)
        feat[f"{label}_keyword_jump"] = ai.get("keyword_jump_avg", 0)
        feat[f"{label}_intertextual_rate"] = ai.get("intertextual_rate", 0)

    # --- 经典 vs 新潮 ---
    for label, d in [("movie", movie), ("book", book)]:
        eo = safe_get(d, "era_orientation", default={})
        feat[f"{label}_era_label"] = eo.get("era_label", "unknown")
        feat[f"{label}_median_year"] = eo.get("median_release_year", 0)
        feat[f"{label}_pct_pre2000"] = eo.get("pct_pre_2000", 0)
        feat[f"{label}_pct_post2015"] = eo.get("pct_post_2015", 0)
        feat[f"{label}_classic_approval"] = eo.get(
            "classic_approval_rate", None)

    # --- 重复标记 ---
    for label, d in [("movie", movie), ("book", book)]:
        dups = safe_get(d, "duplicates", default=[])
        feat[f"{label}_duplicates"] = len(
            dups) if isinstance(dups, list) else 0

    # --- 跨品类重复（书影双收） ---
    cross_dups = data.get("cross_category_duplicates", [])
    feat["cross_dup_count"] = len(
        cross_dups) if isinstance(cross_dups, list) else 0
    feat["cross_dup_samples"] = [d["norm_key"]
                                 for d in cross_dups[:5]] if isinstance(cross_dups, list) else []

    return feat


def main():
    all_feats = []
    for uid in USERS:
        f = extract_features(uid)
        if f:
            all_feats.append(f)

    # 打印对比表
    print(f"\n{'='*120}")
    print(f"豆瓣书影音用户横向对比（{len(all_feats)} 人）")
    print(f"{'='*120}")

    # 表1: 基础量
    print(f"\n{'用户':<18} {'电影':>5} {'图书':>5} {'影/书比':>7} {'想看':>5} {'想读':>5} {'愿望比':>6} {'总计':>6}")
    print("-" * 75)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_count']:>5} {f['book_count']:>5} "
              f"{f['book_ratio']:>7.2f} {f['movie_wish']:>5} {f['book_wish']:>5} "
              f"{f['wish_ratio']:>6.2f} {f['total_collected']:>6}")

    # 表2: 评分风格
    print(f"\n{'用户':<18} {'影均分':>6} {'书均分':>6} {'影4-5星':>7} {'书4-5星':>7} {'影1-2星':>7} {'书1-2星':>7} {'影5星%':>7} {'书5星%':>7}")
    print("-" * 85)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_avg']:>6.2f} {f['book_avg']:>6.2f} "
              f"{f['movie_high_pct']:>7.2f} {f['book_high_pct']:>7.2f} "
              f"{f['movie_low_pct']:>7.2f} {f['book_low_pct']:>7.2f} "
              f"{f['movie_5star_pct']:>7.2f} {f['book_5star_pct']:>7.2f}")

    # 表3: 类型广度
    print(f"\n{'用户':<18} {'影类型':>6} {'书类型':>6} {'影top3%':>8} {'书top3%':>8} {'影第一':>10} {'书第一':>10}")
    print("-" * 85)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_genre_count']:>6} {f['book_genre_count']:>6} "
              f"{f['movie_top3_genre_pct']:>8.2f} {f['book_top3_genre_pct']:>8.2f} "
              f"{f['movie_top_genre']:>10} {f['book_top_genre']:>10}")

    # 表4: 国别
    print(f"\n{'用户':<18} {'影国数':>6} {'书国数':>6} {'影top1%':>8} {'书top1%':>8} {'影国':>8} {'书国':>8}")
    print("-" * 75)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_country_count']:>6} {f['book_country_count']:>6} "
              f"{f['movie_top1_country_pct']:>8.2f} {f['book_top1_country_pct']:>8.2f} "
              f"{f['movie_top_country']:>8} {f['book_top_country']:>8}")

    # 表5: 评论风格
    print(
        f"\n{'用户':<18} {'影评%':>6} {'书评%':>6} {'影评长':>7} {'书评长':>7} {'影周末%':>7} {'书周末%':>7}")
    print("-" * 65)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_comment_pct']:>6.2f} {f['book_comment_pct']:>6.2f} "
              f"{f['movie_avg_comment_len']:>7.0f} {f['book_avg_comment_len']:>7.0f} "
              f"{f['movie_weekend_pct']:>7.2f} {f['book_weekend_pct']:>7.2f}")

    # 表 6: 时间跨度与演化
    print(f"\n{'用户':<18} {'影跨度':>6} {'书跨度':>6} {'影活年':>6} {'书活年':>6} {'影演化':>6} {'书演化':>6} {'跨媒':>5}")
    print("-" * 65)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_year_span']:>6} {f['book_year_span']:>6} "
              f"{f['movie_active_years']:>6} {f['book_active_years']:>6} "
              f"{f['movie_evo_phases']:>6} {f['book_evo_phases']:>6} "
              f"{f['cross_overlaps']:>5}")

    # 表 7: F/T 维度（评论语义 + 类型偏好）
    print(f"\n{'用户':<18} {'影F%':>6} {'影T%':>6} {'影FT':>5} {'影FT#':>6} {'书F%':>6} {'书T%':>6} {'书FT':>5} {'影gfB':>6} {'书gfB':>6}")
    print("-" * 85)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_f_ratio']:>6.2f} {f['movie_t_ratio']:>6.2f} "
              f"{f['movie_ft_leaning']:>5} {f['movie_ft_comments']:>6} "
              f"{f['book_f_ratio']:>6.2f} {f['book_t_ratio']:>6.2f} "
              f"{f['book_ft_leaning']:>5} "
              f"{f['movie_genre_bias']:>6} {f['book_genre_bias']:>6}")

    # 表 8: N/S 维度 + 经典/新潮
    print(f"\n{'用户':<18} {'影N分':>6} {'影NS':>5} {'影文广':>6} {'影互文':>6} {'影年代':>6} {'影经典%':>7} {'影新潮%':>7} {'影era':>5}")
    print("-" * 85)
    for f in all_feats:
        print(f"{f['user_id']:<18} {f['movie_n_score']:>6.3f} {f['movie_ns_leaning']:>5} "
              f"{f['movie_cultural_breadth']:>6.3f} {f['movie_intertextual_rate']:>6.3f} "
              f"{f['movie_median_year']:>6} {f['movie_pct_pre2000']:>7.1f} "
              f"{f['movie_pct_post2015']:>7.1f} {f['movie_era_label']:>5}")

    # 表 9: 重复标记 + 跨品类重复
    print(f"\n{'用户':<18} {'影重复':>6} {'书重复':>6} {'书影双收':>8} {'双收示例'}")
    print("-" * 75)
    for f in all_feats:
        samples = ", ".join(f["cross_dup_samples"][:3])
        print(
            f"{f['user_id']:<18} {f['movie_duplicates']:>6} {f['book_duplicates']:>6} "
            f"{f['cross_dup_count']:>8} {samples}")

    # 保存完整数据
    out = DATA_DIR / "comparison_features.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_feats, f, ensure_ascii=False, indent=2)
    print(f"\n完整特征数据已保存: {out}")


if __name__ == "__main__":
    main()
