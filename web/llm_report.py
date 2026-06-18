"""
报告生成模块

支持两种模式：
1. LLM 生成：使用 OpenAI 兼容 API 生成散文式分析报告
2. 模板降级：无 API key 时使用结构化模板渲染
"""

import json
from typing import Optional

from web import config
from web.mbti_predictor import predict_mbti


def generate_report(analysis: dict) -> str:
    """根据分析 JSON 生成完整报告 HTML。

    优先使用 LLM，无 API key 时降级为模板。
    """
    if config.LLM_API_KEY:
        try:
            return _generate_with_llm(analysis)
        except Exception:
            # LLM 失败时降级
            pass

    return _generate_template(analysis)


# ── LLM 生成 ──────────────────────────────────────────────

def _generate_with_llm(analysis: dict) -> str:
    """调用 OpenAI 兼容 API 生成报告。"""
    from openai import OpenAI

    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
    )

    user_id = analysis.get("user_id", "unknown")

    # 构建精简的分析数据摘要（避免 token 过多）
    summary = _build_analysis_summary(analysis)

    system_prompt = f"""你是一位豆瓣书影音分析专家，正在为用户「{user_id}」撰写一份”自我镜像”报告。

报告写作哲学：
- 报告不是”数据摘要”，而是”自我镜像”——帮助用户认识自己是什么样的人
- 用用户自己的话做镜子：大量引用用户的亲笔评论，展示其思维方式
- 揭示矛盾而非列举偏好：找到品味中的张力
- 追踪核心执念：从高频关键词、反复主题中识别用户真正在思考的问题
- 叙事而非分类：像散文而非报表，每个段落推进对人的理解
- 品味演化 = 一个人的智识成长史
- 语言风格：第二人称、有洞察力、温暖但不廉价、偶尔尖锐

关于 MBTI 人格分析：
- 数据中已提供 MBTI 预测结果（类型 + 各维度置信度），请直接使用这个结论
- 不要自行重新推断 MBTI 类型，而是用数据中的证据来丰富和深化这个判断
- 使用”人格光谱”概念：不是非此即彼，而是”你在 I-E 光谱上的位置偏向...”
- 当某维度置信度较低（<60%）时，重点分析该维度的矛盾信号，这往往是最有趣的洞察
- 每个维度必须用具体数据支撑：引用评论、连接核心执念、对比同类评分

请按以下六个板块递进展开（用 HTML 标签，不用 Markdown）：

1. <section class=”report-section” id=”identity”><h2>你是谁</h2>
   这是整份报告的开篇锤——用户看到的第一件事。
   要求：
   - 先给出四字母类型，然后用一段有力的洞察解释”为什么你是这种人”
   - 使用”人格光谱”表述：不是”你是 I 型”，而是”你在 I-E 光谱上偏向 I 的一侧（置信度 72%）”
   - 当某维度置信度 <60% 时，必须专门分析该维度的矛盾信号（”你在 N/S 之间摇摆，这说明...”）
   - 每个维度必须用具体数据支撑（”你 80% 的五星给了剧情片”而非泛泛而谈）
   - 引用 3-5 条最能体现人格特质的用户评论，做”评论中的人格密码”分析：
     * 选择标准：评论长度 > 50字、包含情感/观点/分析、能体现思维方式
     * 分析方式：不是简单引用，而是解读”这条评论暴露了你什么样的思维模式”
     * 连接维度：每条评论都要关联到具体的 MBTI 维度判断
   - 结尾用一句话概括这个人的核心特质

2. <section class=”report-section” id=”journey”><h2>你的来路</h2>
   品味演化叙事 + 转捩点
   对关键作品名、年份、概念用 <span class=”turning-point”>《书名》</span> 标记
   （渲染为绿色加粗衬线文字，自然融入正文，不要用其他标签包裹书名）

3. <section class=”report-section” id=”obsession”><h2>核心执念</h2>
   贯穿始终的主题 + 用户评论引用（用 <blockquote> 标签）

4. <section class=”report-section” id=”contradiction”><h2>你的矛盾</h2>
   品味中的张力分析

5. <section class=”report-section” id=”unfinished”><h2>你的未完成</h2>
   遗憾清单作为自我许诺

6. <section class=”report-section” id=”recommendations”><h2>你应该看的</h2>
   连接核心关切的推荐 + 推荐理由

只输出 HTML 内容（section 标签），不要包含 <html>、<head>、<body>。"""

    user_prompt = f"以下是用户「{user_id}」的分析数据：\n\n{summary}"

    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4000,
    )

    report_html = response.choices[0].message.content.strip()

    # 确保输出是纯 HTML（去掉可能的 markdown 代码块包裹）
    if report_html.startswith("```"):
        report_html = "\n".join(report_html.split("\n")[1:])
    if report_html.endswith("```"):
        report_html = "\n".join(report_html.split("\n")[:-1])

    return report_html


def _build_analysis_summary(analysis: dict) -> str:
    """构建精简的分析数据摘要，控制 token 数量。"""
    user_id = analysis.get("user_id", "")
    parts = [f"用户: {user_id}\n"]

    # 注入 MBTI 预测结果作为人格骨架
    mbti_pred = analysis.get("mbti_prediction", {})
    if mbti_pred and mbti_pred.get("mbti"):
        mbti = mbti_pred["mbti"]
        conf = mbti_pred.get("confidence", 0)
        method = mbti_pred.get("method", "unknown")
        parts.append(f"【MBTI 预测结果（请以此为基础展开，不要自行重新推断）】")
        parts.append(f"类型: {mbti} (置信度 {conf:.0%}, 方法: {method})")
        dims = mbti_pred.get("dimensions", {})
        for dk in ["IE", "NS", "FT", "JP"]:
            d = dims.get(dk, {})
            if isinstance(d, dict):
                letter = d.get("letter", "?")
                dconf = d.get("confidence", 0)
                parts.append(f"  {dk}: {letter} ({dconf:.0%})")
        parts.append("")

    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        if not d or not d.get("collected_count"):
            continue

        parts.append(f"=== {label} ===")
        parts.append(f"已记录: {d.get('collected_count', 0)} 部/本")
        parts.append(f"想看/读: {d.get('wish_count', 0)}")
        parts.append(f"均分: {d.get('avg_rating', '—')}")

        # 评分分布
        rd = d.get("rating_distribution", {})
        if rd:
            parts.append(f"评分分布: 5星={rd.get('5', 0)} 4星={rd.get('4', 0)} "
                         f"3星={rd.get('3', 0)} 2星={rd.get('2', 0)} 1星={rd.get('1', 0)}")

        # 批量标记数据（MBTI J/P 维度信号）
        bm = d.get("bulk_marking", {})
        if bm:
            parts.append(
                f"批量标记: {bm.get('bulk_days', 0)}天/{bm.get('bulk_pct', 0)}%数据")

        # 年度数据
        yb = d.get("yearly_breakdown", {})
        if yb:
            years_info = []
            for y, v in sorted(yb.items()):
                oc = v.get("organic_count", v.get("count", 0))
                oa = v.get("organic_avg", v.get("avg_rating"))
                if oc > 0:
                    years_info.append(f"{y}({oc}部,{oa or '—'}分)")
            if years_info:
                parts.append(f"年度: {', '.join(years_info[:10])}")

        # 转捩点
        tps = d.get("turning_points", [])
        if tps:
            for tp in tps[:3]:
                parts.append(f"转捩点 {tp['year']}: {tp.get('change_type', '')} "
                             f"(评分 {tp.get('rating_before', '')}→{tp.get('rating_after', '')})")

        # 国别
        cb = d.get("country_breakdown", {})
        if cb:
            top_countries = list(cb.items())[:5]
            parts.append(
                f"国别: {', '.join(f'{c}({n})' for c, n in top_countries)}")

        # 品味演化关键词
        evo = d.get("taste_evolution", [])
        if evo:
            for phase in evo[-5:]:
                kw = phase.get("keywords", [])[:8]
                if kw:
                    parts.append(f"{phase['year']}年关键词: {', '.join(kw)}")

        # 评论情感
        cs = d.get("comment_sentiment", {})
        if cs:
            parts.append(f"评论倾向: {cs.get('leaning', 'balanced')} "
                         f"(F:{cs.get('f_score', 0)} T:{cs.get('t_score', 0)})")

        # ★ 绝对十佳（用户最珍视的作品，报告中应给予最大比重）
        favs = d.get("top_favorites", [])
        if favs:
            parts.append("★ 绝对十佳（用户最珍视的作品，在报告中应重点分析）:")
            for i, f in enumerate(favs[:10], 1):
                cmt = f'\n    评论: "{f["comment"]}"' if f.get("comment") else ""
                parts.append(
                    f"  {i}. 《{f['title']}》({f['rating']}星, "
                    f"{f.get('date', '')[:4]}){cmt}")

        # 最厌恶的作品（低分）
        bottom = d.get("bottom_rated", [])
        if bottom:
            parts.append("最不喜欢的作品:")
            for b in bottom[:5]:
                cmt = f' — "{b["comment"]}"' if b.get("comment") else ""
                parts.append(f"  《{b['title']}》({b['rating']}星){cmt}")

        # 反复给出高分的创作者（导演/作者）
        hp = d.get("hidden_patterns", {})
        creators = hp.get("frequent_creators", {})
        if creators:
            top_creators = list(creators.items())[:10]
            parts.append(
                f"反复给高分的创作者: {', '.join(f'{c}({n}次)' for c, n in top_creators)}")

        # 高分作品的类型分布
        hp_genres = hp.get("genre_distribution", {})
        if hp_genres:
            parts.append(
                f"高分作品类型: {', '.join(f'{g}({n})' for g, n in list(hp_genres.items())[:8])}")

        # 高分作品的评论关键词
        hp_kw = hp.get("comment_keywords", [])
        if hp_kw:
            parts.append(f"高分评论关键词: {', '.join(hp_kw[:15])}")

        # 类型偏好（含实际数据）
        tgb = d.get("top_rated_genre_bias", {})
        if tgb:
            parts.append(f"5星类型偏好: {tgb.get('bias', 'balanced')} "
                         f"(5星中F类={tgb.get('f_pct_top_rated', 0):.0%} T类={tgb.get('t_pct_top_rated', 0):.0%})")

        # 用户评论示例（保留完整）
        samples = d.get("samples", [])
        commented = [s for s in samples if s.get("comment")][:10]
        if commented:
            parts.append("用户亲笔评论:")
            for s in commented:
                parts.append(
                    f"  《{s['title']}》({s.get('rating', '')}星): \"{s['comment'][:300]}\"")

        # 抽象度
        ai = d.get("abstraction_index", {})
        if ai:
            parts.append(
                f"抽象度(N/S): {ai.get('leaning', 'balanced')} (N分={ai.get('n_score', 0)})")

        # 时代
        eo = d.get("era_orientation", {})
        if eo:
            parts.append(f"时代倾向: {eo.get('era_label', 'unknown')} "
                         f"(中位年份={eo.get('median_release_year', '')}, "
                         f"2000前={eo.get('pct_pre_2000', 0)}%)")

        # 遗憾清单
        regrets = d.get("regret_list", [])
        if regrets:
            parts.append(f"遗憾清单({len(regrets)}项):")
            for r in regrets[:5]:
                parts.append(f"  - {r['title']} (已等{r['days_pending']}天)")

        parts.append("")

    # 跨媒体
    cm = analysis.get("cross_media", {})
    if cm:
        overlaps = cm.get("title_overlaps", [])
        if overlaps:
            parts.append(f"跨媒体同名: {', '.join(overlaps[:5])}")
        shared = cm.get("shared_themes", [])
        if shared:
            parts.append(f"跨媒体主题: {', '.join(shared[:5])}")

    return "\n".join(parts)


# ── 模板降级 ──────────────────────────────────────────────────────

def _generate_template(analysis: dict) -> str:
    """基于分析数据生成结构化模板报告（无需 LLM）。"""
    user_id = analysis.get("user_id", "unknown")
    sections = []

    # ── 板块一：你是谁（MBTI，开篇钩子） ──
    sections.append(_template_identity(analysis))

    # ── 板块二：你的来路 ──
    sections.append(_template_journey(analysis))

    # ── 板块三：核心执念 ──
    sections.append(_template_obsession(analysis))

    # ── 板块四：你的矛盾 ──
    sections.append(_template_contradiction(analysis))

    # ── 板块五：你的未完成 ──
    sections.append(_template_unfinished(analysis))

    # ── 板块六：推荐 ──
    sections.append(_template_recommendations(analysis))

    return "\n".join(sections)


def _template_journey(analysis: dict) -> str:
    """模板：你的来路。"""
    html = '<section class="report-section" id="journey"><h2>你的来路</h2>\n'

    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        if not d or not d.get("collected_count"):
            continue

        html += f'<h3>{label}轨迹</h3>\n'
        html += f'<p>你一共记录了 {d["collected_count"]} 部/本作品'
        if d.get("avg_rating"):
            rated = sum(d.get("rating_distribution", {}).values())
            total = d["collected_count"]
            html += f'，其中 {rated} 部/本有评分（{rated*100//total}%），均分 {d["avg_rating"]}'
            if rated * 2 < total:
                html += '。你对大部分作品保持了沉默——这本身也是一种态度'
        html += '。</p>\n'

        # 转捩点
        tps = d.get("turning_points", [])
        if tps:
            html += '<div class="turning-points">\n'
            for tp in tps:
                ct = tp.get("change_type", "")
                ct_label = {"rating_shift": "评分变化",
                            "volume_shift": "数量变化",
                            "rating_and_volume": "双重变化"}.get(ct, ct)
                retro = " (补标期)" if tp.get("is_retroactive") else ""
                html += (f'<span class="turning-point">{tp["year"]}年{retro}</span>'
                         f'：{ct_label}，评分从 {tp.get("rating_before", "—")} '
                         f'变为 {tp.get("rating_after", "—")}\n')
            html += '</div>\n'

    html += '</section>\n'
    return html


def _template_obsession(analysis: dict) -> str:
    """模板：核心执念。"""
    html = '<section class="report-section" id="obsession"><h2>核心执念</h2>\n'

    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        if not d or not d.get("collected_count"):
            continue

        hp = d.get("hidden_patterns", {})
        keywords = hp.get("comment_keywords", [])
        if keywords:
            html += f'<p>你的{label}评论中反复出现的关键词：'
            html += '、'.join(keywords[:10])
            html += '</p>\n'

        # 引用评论
        samples = d.get("samples", [])
        commented = [s for s in samples if s.get("comment")][:5]
        if commented:
            html += '<div class="quotes">\n'
            for s in commented:
                html += f'<blockquote><p>"{s["comment"]}"</p>'
                html += f'<cite>—— 评《{s["title"]}》</cite></blockquote>\n'
            html += '</div>\n'

    html += '</section>\n'
    return html


def _template_contradiction(analysis: dict) -> str:
    """模板：你的矛盾。"""
    html = '<section class="report-section" id="contradiction"><h2>你的矛盾</h2>\n'

    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        if not d or not d.get("collected_count"):
            continue

        cs = d.get("comment_sentiment", {})
        tgb = d.get("top_rated_genre_bias", {})

        if cs and tgb:
            ft = cs.get("leaning", "balanced")
            gb = tgb.get("bias", "balanced")
            if ft != gb and ft != "balanced" and gb != "balanced":
                html += (f'<p>有趣的张力：你的评论风格偏向 {ft}（'
                         f'{"感性" if ft == "F" else "理性"}），'
                         f'但你的 5 星作品类型偏好偏向 {gb}（'
                         f'{"感性" if gb == "F" else "理性"}）。</p>\n')

    html += '</section>\n'
    return html


def _template_identity(analysis: dict) -> str:
    """模板：你是谁（MBTI 推断）。

    使用 mbti_predictor 的统一预测结果，避免重复推断。
    输出人格光谱概念、置信度、数据依据和评论深度引用。
    """
    html = '<section class="report-section" id="identity"><h2>你是谁</h2>\n'

    # 调用统一预测器（含 ML + 规则混合策略）
    try:
        pred = predict_mbti(analysis)
    except Exception:
        pred = {"mbti": "XXXX", "confidence": 0, "dimensions": {}, "method": "error"}

    mbti_str = pred.get("mbti", "XXXX")
    avg_confidence = int(pred.get("confidence", 0) * 100)
    dims = pred.get("dimensions", {})
    method = pred.get("method", "rules_only")

    # 经典/新潮
    era_label = ""
    for dtype in ["movie", "book"]:
        d = analysis.get(dtype, {})
        eo = d.get("era_orientation", {})
        if eo:
            era_label = eo.get("era_label", "")
            break
    era_text = {"TC": "经典倾向", "TN": "新潮倾向", "TB": "平衡"}.get(era_label, "")

    # 输出：人格光谱概念
    html += f'<div class="mbti-badge">{mbti_str}</div>\n'
    html += f'<p class="mbti-confidence">综合置信度 {avg_confidence}%（{method}）</p>\n'
    html += '<p class="spectrum-note">人格不是非此即彼的标签，而是你在光谱上的位置。</p>\n'
    if era_text:
        html += f'<p class="era-note">时代倾向：{era_text}</p>\n'

    # 四维度解读（人格光谱版本）
    html += '<div class="dimension-explain">\n'
    dim_labels = [
        (0, "I", "E", "内向 (I)", "外向 (E)",
         "你倾向于在独处中沉浸于作品，思考多于表达",
         "你乐于分享观影感受，表达欲较强"),
        (1, "N", "S", "直觉 (N)", "感觉 (S)",
         "你关注主题、隐喻和概念层面的东西",
         "你更在意具体体验：表演、画面、情节、文笔"),
        (2, "F", "T", "情感 (F)", "思考 (T)",
         "你更被人性和情感打动，作品对你来说是感受的镜子",
         "你更被结构和技巧说服，作品对你来说是智识的拼图"),
        (3, "J", "P", "判断 (J)", "感知 (P)",
         "你有明确的品味标准，标记习惯整洁有条理",
         "你保持开放，想看列表不断增长，不急于归类"),
    ]
    dim_keys = ["IE", "NS", "FT", "JP"]

    for i, (idx, a, b, la, lb, desc_a, desc_b) in enumerate(dim_labels):
        dk = dim_keys[idx]
        dim_info = dims.get(dk, {})
        letter = mbti_str[idx] if idx < len(mbti_str) else "X"
        conf = int(dim_info.get("confidence", 0.5) * 100) if isinstance(dim_info, dict) else 50

        if letter == "X":
            html += f'<p><strong>{la} / {lb}</strong>：倾向不明确</p>\n'
        elif letter == a:
            # 人格光谱表述
            if conf < 60:
                html += (f'<p><strong>{la}</strong> <span class="dim-conf">{conf}%</span>：'
                         f'你在 {a}-{b} 光谱上略微偏向 {a} 的一侧，但信号不够强烈。'
                         f'{desc_a}</p>\n')
            else:
                html += (f'<p><strong>{la}</strong> <span class="dim-conf">{conf}%</span>：'
                         f'你在 {a}-{b} 光谱上明显偏向 {a} 的一侧。'
                         f'{desc_a}</p>\n')
        else:
            if conf < 60:
                html += (f'<p><strong>{lb}</strong> <span class="dim-conf">{conf}%</span>：'
                         f'你在 {a}-{b} 光谱上略微偏向 {b} 的一侧，但信号不够强烈。'
                         f'{desc_b}</p>\n')
            else:
                html += (f'<p><strong>{lb}</strong> <span class="dim-conf">{conf}%</span>：'
                         f'你在 {a}-{b} 光谱上明显偏向 {b} 的一侧。'
                         f'{desc_b}</p>\n')
    html += '</div>\n'

    # 评论中的人格密码（深度引用）
    html += _template_comment_analysis(analysis)

    html += '</section>\n'
    return html


def _template_comment_analysis(analysis: dict) -> str:
    """模板：评论中的人格密码。

    选择最能体现人格特质的评论，做深度分析。
    选择标准：评论长度 > 50字、包含情感/观点/分析、能体现思维方式。
    """
    html = '<div class="comment-personality">\n<h3>评论中的人格密码</h3>\n'

    # 收集所有有评论的样本
    all_comments = []
    for dtype in ["movie", "book"]:
        d = analysis.get(dtype, {})
        samples = d.get("samples", [])
        for s in samples:
            comment = s.get("comment", "")
            # 只选有意义的评论（长度 > 50字）
            if comment and len(comment) > 50:
                all_comments.append({
                    "title": s.get("title", ""),
                    "comment": comment,
                    "rating": s.get("rating", 0),
                    "type": dtype,
                    "length": len(comment),
                })

    if not all_comments:
        html += '<p>你很少留下评论——沉默本身也是一种态度。</p>\n'
    else:
        # 选择策略：优先选择长评论，但也要保证多样性
        # 1. 按长度排序，取前 10 条候选
        all_comments.sort(key=lambda x: x["length"], reverse=True)
        candidates = all_comments[:10]

        # 2. 从候选中选 5 条，确保电影和书籍都有代表
        movie_comments = [c for c in candidates if c["type"] == "movie"]
        book_comments = [c for c in candidates if c["type"] == "book"]

        selected = []
        # 各选最多 3 条电影、2 条书籍（或反过来，取决于哪个多）
        if len(movie_comments) >= len(book_comments):
            selected.extend(movie_comments[:3])
            selected.extend(book_comments[:2])
        else:
            selected.extend(book_comments[:3])
            selected.extend(movie_comments[:2])

        # 如果还不够 5 条，从剩余候选中补充
        if len(selected) < 5:
            remaining = [c for c in candidates if c not in selected]
            selected.extend(remaining[:5 - len(selected)])

        html += '<p>以下是你最能体现思维方式的评论：</p>\n'
        html += '<div class="quotes">\n'
        for c in selected[:5]:
            type_label = "观影" if c["type"] == "movie" else "阅读"
            # 截取前 200 字，避免过长
            display_comment = c["comment"][:200]
            if len(c["comment"]) > 200:
                display_comment += "..."
            html += (f'<blockquote class="personality-quote">'
                     f'<p>"{display_comment}"</p>'
                     f'<cite>—— {type_label}《{c["title"]}》({c["rating"]}星)</cite>'
                     f'</blockquote>\n')
        html += '</div>\n'

    html += '</div>\n'
    return html


def _template_unfinished(analysis: dict) -> str:
    """模板：你的未完成。"""
    html = '<section class="report-section" id="unfinished"><h2>你的未完成</h2>\n'

    regrets_found = False
    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        regrets = d.get("regret_list", [])
        if regrets:
            regrets_found = True
            html += f'<h3>{label}遗憾</h3>\n'
            html += '<ul class="regret-list">\n'
            for r in regrets[:10]:
                years = r["days_pending"] // 365
                html += (f'<li>《{r["title"]}》—— '
                         f'已等 {years} 年（{r["days_pending"]} 天）</li>\n')
            html += '</ul>\n'

    if not regrets_found:
        html += '<p>你的待看/待读列表中暂无超过两年的条目——你是一个说到做到的人。</p>\n'

    html += '</section>\n'
    return html


def _template_recommendations(analysis: dict) -> str:
    """模板：推荐。"""
    html = '<section class="report-section" id="recommendations"><h2>你应该看的</h2>\n'

    # 基于 wish 列表中的高分潜力作品推荐
    for dtype, label in [("movie", "观影"), ("book", "阅读")]:
        d = analysis.get(dtype, {})
        wish_samples = d.get("wish_samples", [])
        if wish_samples:
            html += f'<h3>{label}推荐（来自你的想看/想读列表）</h3>\n'
            html += '<ul class="rec-list">\n'
            for w in wish_samples[:5]:
                title = w.get("title", "")
                info = w.get("info", "")[:80]
                html += f'<li>《{title}》'
                if info:
                    html += f'<span class="rec-info">{info}</span>'
                html += '</li>\n'
            html += '</ul>\n'

    html += '</section>\n'
    return html
