"""
豆瓣数据分析器

读取豆瓣导出的 CSV 文件，生成结构化分析数据（JSON），
供 LLM 进一步生成用户画像、品味报告、推荐等。

用法:
  python analyzer.py <用户ID> [--dir CSV目录] [--output 输出JSON路径]

输出 JSON 包含:
  - 基础统计（数量、评分分布、年度/月度趋势）
  - 观影/阅读节奏（星期分布）
  - 高分作品特征
  - 品味演化（按年分段）
  - 遗憾清单（wish 列表中年代久远的条目）
  - 跨媒体关联
  - 社交卡片数据
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────

FIELDS = ["title", "rating", "date", "info", "comment", "poster", "link"]

FILE_MAP = {
    ("movie", "collected"): "movies",
    ("movie", "wish"):      "movie_wish",
    ("book",  "collected"): "books",
    ("book",  "wish"):      "book_wish",
    ("music", "collected"): "music",
    ("music", "wish"):      "music_wish",
}

# 类型映射
TYPE_LABELS = {"movie": "观影", "book": "阅读", "music": "聆听"}
TYPE_UNITS = {"movie": "部", "book": "本", "music": "张"}
ALL_TYPES = ["movie", "book", "music"]

# 音乐数据稀疏阈值
MUSIC_SPARSE_THRESHOLD = 20

STOPWORDS = set(
    "的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 "
    "没有 看 好 自己 这 他 她 它 们 那 什么 没 但 还 很 非常 比较 一般 觉得 "
    "可能 应该 这个 那个 可以 因为 所以 而且 虽然 但是 如果 已经 之后 之前 "
    "以及 或者 而且 不过 然后 其实 真的 比较 有点 太 最 更 还是 "
    # 影视/图书元数据噪音词
    "分钟 小时 导演 编剧 主演 制片 出品 发行 粤语 汉语 普通话 英语 日语 "
    "韩语 法语 德语 西班牙语 意大利语 俄语 波斯语 闽南语 客家话 方言 "
    "出版社 出版 大学 研究 理论 分析 哲学 思想 概念 问题 "
    "电影 剧情 喜剧 动作 爱情 惊悚 犯罪 战争 科幻 动画 纪录 短片 "
    "历史 传记 悬疑 冒险 家庭 奇幻 恐怖 同性 情色 歌舞 武侠 古装 "
    "音乐 西部 灾难 儿童 西部".split()
)

# 电影 info 中的国家/地区词典（用于从 / 分隔的字段中识别国家）
COUNTRIES = {
    # 亚洲
    "中国大陆", "中国", "中国香港", "中国台湾", "中国澳门",
    "日本", "韩国", "朝鲜", "越南", "泰国", "菲律宾", "印度",
    "印度尼西亚", "马来西亚", "新加坡", "蒙古", "伊朗", "伊拉克",
    "以色列", "巴勒斯坦", "黎巴嫩", "叙利亚", "土耳其", "沙特阿拉伯",
    "阿富汗", "格鲁吉亚", "亚美尼亚", "阿塞拜疆", "哈萨克斯坦",
    # 欧洲
    "法国", "德国", "英国", "意大利", "西班牙", "葡萄牙", "荷兰",
    "比利时", "瑞士", "奥地利", "瑞典", "挪威", "丹麦", "芬兰",
    "冰岛", "爱尔兰", "卢森堡", "波兰", "捷克", "斯洛伐克", "匈牙利",
    "罗马尼亚", "保加利亚", "塞尔维亚", "克罗地亚", "斯洛文尼亚",
    "波黑", "阿尔巴尼亚", "希腊", "俄罗斯", "苏联", "乌克兰",
    "白俄罗斯", "爱沙尼亚", "拉脱维亚", "立陶宛",
    # 美洲
    "美国", "加拿大", "墨西哥", "巴西", "阿根廷", "智利", "哥伦比亚",
    "秘鲁", "古巴", "委内瑞拉", "乌拉圭", "玻利维亚", "厄瓜多尔",
    # 大洋洲
    "澳大利亚", "新西兰",
    # 非洲
    "南非", "埃及", "摩洛哥", "突尼斯", "尼日利亚", "塞内加尔",
    "阿尔及利亚", "肯尼亚", "埃塞俄比亚",
}

# 图书 info 中的国家代码映射
BOOK_COUNTRY_CODES = {
    "日": "日本", "美": "美国", "英": "英国", "法": "法国", "德": "德国",
    "意": "意大利", "西": "西班牙", "俄": "俄罗斯", "韩": "韩国",
    "加": "加拿大", "澳": "澳大利亚", "以": "以色列", "荷": "荷兰",
    "比": "比利时", "瑞典": "瑞典", "瑞士": "瑞士", "奥地利": "奥地利",
    "波兰": "波兰", "捷克": "捷克", "爱尔兰": "爱尔兰", "墨": "墨西哥",
    "巴西": "巴西", "阿根廷": "阿根廷", "智利": "智利", "南非": "南非",
    "哥伦比亚": "哥伦比亚", "挪威": "挪威", "丹麦": "丹麦", "芬兰": "芬兰",
    "清": "中国", "古希腊": "古希腊", "古罗马": "古罗马",
}

# 电影类型识别模式
GENRE_KEYWORDS = [
    "剧情", "喜剧", "动作", "爱情", "惊悚", "犯罪", "战争", "科幻",
    "动画", "纪录片", "短片", "历史", "传记", "悬疑", "冒险", "家庭",
    "奇幻", "恐怖", "同性", "情色", "歌舞", "武侠", "古装", "音乐",
    "西部", "灾难", "儿童", "运动", "黑色电影",
]

DAY_NAMES_ZH = {
    0: "周一", 1: "周二", 2: "周三", 3: "周四",
    4: "周五", 5: "周六", 6: "周日",
}

MONTH_NAMES_ZH = [
    "", "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]

# 每类最多采样数
MAX_SAMPLES = 150

# ── F/T 维度词库 ────────────────────────────────────────────────
# F（感性/价值轴）：被人性、情感、生命体验打动
F_WORDS = set(
    "感动 共鸣 人性 温暖 真诚 善良 痛苦 孤独 爱 意义 生命 存在 "
    "悲伤 眼泪 治愈 温柔 纯真 深情 心疼 脆弱 敏感 灵魂 情感 "
    "美好 希望 梦想 自由 勇气 坚持 成长 青春 记忆 回忆 怀念 "
    "亲情 友情 爱情 浪漫 天真 纯粹 朴素 坦诚 质朴 平凡 日常 "
    "生活 人生 命运 死亡 离别 重逢 救赎 宽恕 理解 包容 慈悲 "
    "挣扎 苦难 牺牲 奉献 牵挂 羁绊 陪伴 守候 等待 守望 "
    "细腻 含蓄 深沉 克制 隐忍 沉默 无言 留白 余韵 隽永".split()
)

# T（理性/逻辑轴）：被结构、技巧、系统性说服
T_WORDS = set(
    "结构 逻辑 设定 技巧 手法 漏洞 合理 框架 系统 叙事 调度 "
    "节奏 剪辑 摄影 构图 配乐 美术 特效 剧本 台词 对白 "
    "铺垫 伏笔 反转 悬念 张力 冲突 高潮 收束 呼应 对照 "
    "风格 类型 类型片 实验 先锋 前卫 形式 形式感 作者性 "
    "隐喻 象征 意象 寓言 解构 互文 致敬 戏仿 改编 原著 "
    "表演 演技 诠释 塑造 刻画 呈现 表达 探讨 探索 尝试 "
    "完成度 成熟 精准 犀利 老练 工整 严谨 克制 冷静 客观 "
    "黑色幽默 荒诞 讽刺 批判 反思 审视 剖析 洞察 深刻 锐利".split()
)

# F 倾向电影类型
F_GENRES = {"剧情", "传记", "爱情", "家庭", "动画", "音乐", "歌舞", "儿童"}
# T 倾向电影类型
T_GENRES = {"科幻", "悬疑", "犯罪", "惊悚", "恐怖", "战争", "纪录片", "短片", "黑色电影"}

# 互文引用模式（N/S 维度用）
INTERTEXTUAL_PATTERNS = [
    r"让我想到", r"像.*一样", r"类似", r" reminiscent", r"让人联想起",
    r"不禁想起", r"如同", r"仿佛", r"有点像", r"神似",
    r"致敬", r"互文", r"参考了", r"受.*影响", r"延续了",
]


# ── CSV 读取 ──────────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    """读取豆瓣导出 CSV（UTF-8 BOM），返回 dict 列表。"""
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        items = []
        for row in reader:
            # 将中文表头映射回英文 key
            item = {}
            header_map = {"片名": "title", "书名": "title", "评分": "rating",
                          "日期": "date", "简介": "info", "短评": "comment",
                          "封面": "poster", "海报": "poster", "链接": "link"}
            for k, v in row.items():
                mapped = header_map.get(k.strip(), k.strip())
                item[mapped] = (v or "").strip()
            items.append(item)
        return items


# ── 解析辅助 ──────────────────────────────────────────────────

def parse_rating(r: str) -> int | None:
    """将评分字符串转为整数 1-5，无效返回 None。"""
    if not r:
        return None
    try:
        v = int(r)
        return v if 1 <= v <= 5 else None
    except (ValueError, TypeError):
        return None


def parse_date(d: str) -> datetime | None:
    """解析 YYYY-MM-DD 日期。"""
    if not d:
        return None
    try:
        return datetime.strptime(d.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def extract_year(info: str) -> str | None:
    """从简介中提取年份。"""
    if not info:
        return None
    m = re.search(r"(19\d{2}|20\d{2})", info)
    return m.group(1) if m else None


def _parse_movie_info(info: str) -> dict:
    """解析电影 info 字段，提取国家、导演、类型、语言。

    豆瓣电影 info 格式:
    date(country) / actor1 / ... / country1 / country2 / director1 / director2 /
    title / duration(分钟) / genre1 / genre2 / language
    """
    if not info:
        return {"countries": [], "directors": [], "genres": [], "languages": []}

    parts = [p.strip() for p in re.split(r"\s*/\s*", info)]
    countries, directors, genres, languages = [], [], [], []

    # 跳过第一个（日期字段）
    start = 0
    if parts and re.match(r"\d{4}", parts[0]):
        start = 1

    # 分类每个字段
    found_country = False
    past_country = False
    for part in parts[start:]:
        # 跳过 URL、标题、时长
        if re.match(r"https?://", part) or re.match(r"www\.", part):
            continue
        if re.search(r"\d+\s*分钟", part):
            past_country = True
            continue

        # 检查是否为国家
        if part in COUNTRIES:
            countries.append(part)
            found_country = True
            continue

        # 检查是否为类型
        if part in GENRE_KEYWORDS:
            genres.append(part)
            continue

        # 检查是否为语言（常见语言模式）
        if re.match(r"^(汉语|英语|日语|韩语|法语|德语|西班牙语|意大利语|俄语|"
                    r"波斯语|粤语|闽南语|客家话|普通话|方言|葡萄牙语|荷兰语|"
                    r"瑞典语|阿拉伯语|波兰语|捷克语|泰语|印地语|土耳其语)$", part):
            languages.append(part)
            continue

        # 如果已经找到国家，且不是国家，则认为是导演/演员
        # 策略：国家之后的非类型字段 = 导演
        if found_country and not past_country and not genres:
            # 去除 "导演名 English Name" 格式
            name = re.sub(r"\s+[A-Z].*$", "", part).strip()
            if name and len(name) >= 2 and name not in COUNTRIES:
                directors.append(name)

    return {
        "countries": countries,
        "directors": directors[:3],  # 最多3个
        "genres": genres,
        "languages": languages,
    }


def _parse_book_info(info: str) -> dict:
    """解析图书 info 字段，提取作者、出版社。

    豆瓣图书 info 格式:
    [country_code] author / translator / publisher / date / price
    """
    if not info:
        return {"author": "", "publisher": "", "country": ""}

    parts = [p.strip() for p in re.split(r"\s*/\s*", info)]
    author, publisher, country = "", "", ""

    # 提取方括号中的国家代码
    if parts:
        m = re.match(r"\[([^\]]+)\]\s*(.*)", parts[0])
        if m:
            code = m.group(1).strip()
            author = m.group(2).strip()
            country = BOOK_COUNTRY_CODES.get(code, code)
        else:
            author = parts[0]

    # 提取出版社（包含"出版社"的字段）
    for part in parts[1:]:
        if "出版社" in part or "出版公司" in part:
            publisher = part
            break

    return {"author": author, "publisher": publisher, "country": country}


def extract_country(info: str) -> str | None:
    """从简介中提取国家/地区。"""
    if not info:
        return None
    # 先尝试电影格式
    parsed = _parse_movie_info(info)
    if parsed["countries"]:
        return parsed["countries"][0]
    # 再尝试图书格式
    book = _parse_book_info(info)
    if book["country"]:
        return book["country"]
    return None


def extract_director_or_author(info: str) -> str:
    """从简介中提取导演（电影）或作者（图书）。"""
    if not info:
        return ""
    # 先尝试电影格式
    parsed = _parse_movie_info(info)
    if parsed["directors"]:
        return parsed["directors"][0]
    # 再尝试图书格式
    book = _parse_book_info(info)
    if book["author"]:
        return book["author"]
    return ""


def extract_genres(info: str) -> list[str]:
    """从电影简介中提取类型标签。"""
    if not info:
        return []
    parsed = _parse_movie_info(info)
    return parsed["genres"]


def tokenize_zh(text: str) -> list[str]:
    """简易中文分词：提取 2-4 字连续词组，过滤噪音。"""
    if not text:
        return []
    # 去除标点和纯数字/字母段
    text = re.sub(r"[^\u4e00-\u9fff]", " ", text)
    words = []
    for seg in text.split():
        if len(seg) <= 1:
            continue
        for n in (4, 3, 2):
            for i in range(len(seg) - n + 1):
                w = seg[i:i + n]
                # 过滤纯数字或过短的无意义片段
                if re.match(r"^\d+$", w):
                    continue
                if w not in STOPWORDS:
                    words.append(w)
    return words


# ── 批量标记检测 ──────────────────────────────────────────────

def detect_bulk_marking(items: list[dict]) -> dict:
    """检测批量标记日，返回 bulk_dates 集合和统计信息。

    批量标记日 = 单日标记量 >= 5 的日期。
    这些日期很可能是在整理旧标记而非当天观看/阅读。
    """
    date_counts: dict[str, int] = Counter()
    for it in items:
        d = it.get("date", "")
        if d:
            date_counts[d] += 1

    if not date_counts:
        return {"bulk_dates": set(), "threshold": 0,
                "bulk_days": 0, "bulk_items": 0, "bulk_pct": 0,
                "top_bulk_days": []}

    threshold = 5  # 一天标 5 条及以上算批量

    bulk_dates = {d for d, c in date_counts.items() if c >= threshold}
    bulk_items = sum(date_counts[d] for d in bulk_dates)

    # 批量日 Top 10（用于报告展示）
    top_bulk = sorted(
        [(d, date_counts[d]) for d in bulk_dates],
        key=lambda x: -x[1]
    )[:10]

    return {
        "bulk_dates": bulk_dates,
        "threshold": threshold,
        "bulk_days": len(bulk_dates),
        "bulk_items": bulk_items,
        "bulk_pct": round(bulk_items / len(items) * 100, 1) if items else 0,
        "top_bulk_days": [{"date": d, "count": c} for d, c in top_bulk],
    }


def filter_bulk_items(items: list[dict], bulk_dates: set) -> list[dict]:
    """过滤掉批量标记日的条目，只保留'有机'标记。"""
    if not bulk_dates:
        return items
    return [it for it in items if it.get("date", "") not in bulk_dates]


# ── 补标洪水检测 ────────────────────────────────────────────────

def retroactive_analysis(items: list[dict], lag_threshold: int = 5) -> dict:
    """检测补标洪水期：区分回忆性标记和实时标记。

    核心逻辑：比较「标记日期」与「作品发行年份」的时间差（lag）。
    如果某月标记的作品中位 lag > lag_threshold 年，该月判定为补标月。

    返回：
      - retroactive_months: 补标月列表
      - organic_start: 有机期起点（"YYYY-MM" 或 None）
      - retroactive_pct: 补标月占总月数的百分比
    """
    monthly_lags: dict[str, list[int]] = defaultdict(list)

    for it in items:
        mark_dt = parse_date(it.get("date", ""))
        release_year_str = extract_year(it.get("info", ""))
        if mark_dt and release_year_str:
            try:
                release_y = int(release_year_str)
                lag = mark_dt.year - release_y
                if 0 <= lag <= 100:
                    month_key = f"{mark_dt.year}-{mark_dt.month:02d}"
                    monthly_lags[month_key].append(lag)
            except (ValueError, TypeError):
                continue

    if not monthly_lags:
        return {"retroactive_months": [], "organic_start": None,
                "retroactive_pct": 0, "lag_threshold": lag_threshold}

    sorted_months = sorted(monthly_lags.keys())
    retro_months = []
    organic_months = []

    for m in sorted_months:
        lags = sorted(monthly_lags[m])
        median_lag = lags[len(lags) // 2]
        count = len(lags)
        entry = {"month": m, "median_lag": median_lag, "count": count}
        if median_lag > lag_threshold:
            entry["type"] = "retroactive"
            retro_months.append(entry)
        else:
            entry["type"] = "organic"
            organic_months.append(entry)

    # 有机期起点：第一个有机月
    organic_start = None
    if organic_months:
        organic_start = organic_months[0]["month"]

    total_months = len(sorted_months)
    retro_pct = round(len(retro_months) / total_months *
                      100, 1) if total_months else 0

    return {
        "retroactive_months": retro_months,
        "organic_start": organic_start,
        "retroactive_pct": retro_pct,
        "lag_threshold": lag_threshold,
        "total_marked_months": total_months,
        "retroactive_month_count": len(retro_months),
    }


# ── F/T 维度：评论语义分析 ────────────────────────────────────

def comment_sentiment(items: list[dict]) -> dict:
    """分析评论中的 F/T 倾向：被人性打动(F) vs 被逻辑说服(T)。

    对每条评论做关键词分类，汇总 F_score 和 T_score，
    返回整体倾向、分评论得分、以及采样示例。
    """
    total_f, total_t = 0, 0
    scored_comments = []  # 有得分的评论

    for it in items:
        comment = it.get("comment", "")
        if not comment or len(comment) < 4:
            continue

        f_hits, t_hits = [], []
        for w in F_WORDS:
            if w in comment:
                f_hits.append(w)
                total_f += 1
        for w in T_WORDS:
            if w in comment:
                t_hits.append(w)
                total_t += 1

        if f_hits or t_hits:
            scored_comments.append({
                "title": it.get("title", ""),
                "comment": comment[:200],
                "f_score": len(f_hits),
                "t_score": len(t_hits),
                "f_words": f_hits[:5],
                "t_words": t_hits[:5],
            })

    total = total_f + total_t
    f_ratio = round(total_f / total, 3) if total else 0.5
    t_ratio = round(total_t / total, 3) if total else 0.5

    # 判定倾向：差值超过 0.1 才算有明确倾向
    if f_ratio - t_ratio > 0.1:
        leaning = "F"
    elif t_ratio - f_ratio > 0.1:
        leaning = "T"
    else:
        leaning = "balanced"

    # F/T 得分最高的评论示例
    f_exemplars = sorted(
        [c for c in scored_comments if c["f_score"] > c["t_score"]],
        key=lambda x: -x["f_score"]
    )[:5]
    t_exemplars = sorted(
        [c for c in scored_comments if c["t_score"] > c["f_score"]],
        key=lambda x: -x["t_score"]
    )[:5]

    return {
        "f_score": total_f,
        "t_score": total_t,
        "f_ratio": f_ratio,
        "t_ratio": t_ratio,
        "leaning": leaning,
        "comment_count": len(scored_comments),
        "f_exemplars": f_exemplars,
        "t_exemplars": t_exemplars,
    }


# ── F/T 维度：top_rated 类型偏好 ────────────────────────────────

def top_rated_genre_bias(items: list[dict]) -> dict:
    """分析用户 5 星作品的类型标签，判断 F/T 倾向。

    对比 top_rated (5星) vs 整体的 genre 分布差异。
    F 倾向类型：剧情、传记、爱情、家庭
    T 倾向类型：科幻、悬疑、犯罪、实验
    """
    # 整体 genre 分布
    all_genres = Counter()
    for it in items:
        for g in extract_genres(it.get("info", "")):
            all_genres[g] += 1

    # 5 星作品 genre 分布
    five_star = [it for it in items if parse_rating(it.get("rating", "")) == 5]
    top_genres = Counter()
    for it in five_star:
        for g in extract_genres(it.get("info", "")):
            top_genres[g] += 1

    # 计算 F/T 得分
    all_total = sum(all_genres.values()) or 1
    top_total = sum(top_genres.values()) or 1

    f_score_all = sum(all_genres[g] for g in F_GENRES if g in all_genres)
    t_score_all = sum(all_genres[g] for g in T_GENRES if g in all_genres)
    f_score_top = sum(top_genres[g] for g in F_GENRES if g in top_genres)
    t_score_top = sum(top_genres[g] for g in T_GENRES if g in top_genres)

    f_pct_all = round(f_score_all / all_total, 3)
    t_pct_all = round(t_score_all / all_total, 3)
    f_pct_top = round(f_score_top / top_total, 3) if top_total else 0
    t_pct_top = round(t_score_top / top_total, 3) if top_total else 0

    # 5星中的 F/T 浓度 vs 整体的差异
    f_lift = round(f_pct_top - f_pct_all, 3)
    t_lift = round(t_pct_top - t_pct_all, 3)

    if f_lift > 0.05 and f_lift > t_lift:
        bias = "F"
    elif t_lift > 0.05 and t_lift > f_lift:
        bias = "T"
    else:
        bias = "balanced"

    return {
        "five_star_count": len(five_star),
        "f_pct_overall": f_pct_all,
        "t_pct_overall": t_pct_all,
        "f_pct_top_rated": f_pct_top,
        "t_pct_top_rated": t_pct_top,
        "f_lift": f_lift,
        "t_lift": t_lift,
        "bias": bias,
        "top_genres": dict(top_genres.most_common(10)),
        "all_genres": dict(all_genres.most_common(10)),
    }


# ── N/S 维度：抽象度指标 ────────────────────────────────────────

def abstraction_index(items: list[dict], evolution: list[dict],
                      country_data: dict) -> dict:
    """衡量用户的抽象度 / 具象度 (N/S)。

    三个子指标：
    1. 跳跃性：品味演化阶段间关键词变化幅度
    2. 文化广度：国别分布的分散度
    3. 联想性：评论中互文引用频率
    """
    # 1. 跳跃性：相邻年份间关键词的 Jaccard 距离
    jumps = []
    if len(evolution) >= 2:
        for i in range(1, len(evolution)):
            prev_kw = set(evolution[i - 1].get("keywords", []))
            curr_kw = set(evolution[i].get("keywords", []))
            if prev_kw or curr_kw:
                union = prev_kw | curr_kw
                intersect = prev_kw & curr_kw
                jaccard_dist = 1 - len(intersect) / len(union) if union else 0
                jumps.append(jaccard_dist)

    avg_jump = round(sum(jumps) / len(jumps), 3) if jumps else 0

    # 2. 文化广度：国别分布的 Shannon 炳（归一化）
    import math
    total_c = sum(country_data.values()) if country_data else 0
    if total_c > 0 and len(country_data) > 1:
        entropy = -sum(
            (v / total_c) * math.log2(v / total_c)
            for v in country_data.values() if v > 0
        )
        max_entropy = math.log2(len(country_data))
        cultural_breadth = round(
            entropy / max_entropy, 3) if max_entropy > 0 else 0
    else:
        entropy = 0
        cultural_breadth = 0

    # 3. 联想性：评论中互文引用频率
    intertextual_count = 0
    total_comments = 0
    for it in items:
        comment = it.get("comment", "")
        if not comment or len(comment) < 4:
            continue
        total_comments += 1
        for pat in INTERTEXTUAL_PATTERNS:
            if re.search(pat, comment):
                intertextual_count += 1
                break  # 每条评论只计一次

    intertextual_rate = round(
        intertextual_count / total_comments, 3
    ) if total_comments > 0 else 0

    # 综合 N 得分（0-1，越高越抽象/直觉型）
    n_score = round((avg_jump * 0.4 + cultural_breadth * 0.3 +
                     min(intertextual_rate * 5, 1) * 0.3), 3)

    if n_score > 0.55:
        leaning = "N"
    elif n_score < 0.35:
        leaning = "S"
    else:
        leaning = "balanced"

    return {
        "keyword_jump_avg": avg_jump,
        "keyword_jumps": [round(j, 3) for j in jumps],
        "cultural_entropy": round(entropy, 3),
        "cultural_breadth": cultural_breadth,
        "country_count": len(country_data),
        "intertextual_count": intertextual_count,
        "intertextual_rate": intertextual_rate,
        "total_comments_analyzed": total_comments,
        "n_score": n_score,
        "leaning": leaning,
    }


# ── 经典 vs 新潮轴 ─────────────────────────────────────────────

def era_orientation(items: list[dict]) -> dict:
    """分析用户观看/阅读作品的发行年代分布，判断经典 vs 新潮倾向。

    计算：
    - median_release_year: 加权中位数年份
    - release_year_spread: IQR (四分位距)
    - pct_pre_2000: 2000年前作品占比
    - pct_post_2015: 2015年后作品占比
    - era_label: TC(经典) / TN(新潮) / TB(平衡)
    """
    release_years = []
    release_years_rated = []  # 有评分的

    for it in items:
        year_str = extract_year(it.get("info", ""))
        if year_str:
            try:
                y = int(year_str)
                if 1900 <= y <= 2030:
                    release_years.append(y)
                    if parse_rating(it.get("rating", "")) is not None:
                        release_years_rated.append(y)
            except (ValueError, TypeError):
                continue

    if not release_years:
        return {"era_label": "unknown", "release_year_count": 0}

    release_years.sort()
    n = len(release_years)

    # 中位数
    median_year = release_years[n // 2]

    # IQR
    q1 = release_years[n // 4]
    q3 = release_years[3 * n // 4]
    spread = q3 - q1

    # 百分比
    pct_pre_2000 = round(
        sum(1 for y in release_years if y < 2000) / n * 100, 1)
    pct_post_2015 = round(
        sum(1 for y in release_years if y >= 2015) / n * 100, 1)
    pct_classic = round(
        sum(1 for y in release_years if y <= datetime.now().year - 20)
        / n * 100, 1
    )

    # 判定倾向
    if pct_pre_2000 > 40:
        era_label = "TC"  # 经典倾向
    elif pct_post_2015 > 50:
        era_label = "TN"  # 新潮倾向
    else:
        era_label = "TB"  # 平衡

    # 高分经典 vs 低分经典（区分主动选择 vs 被动观看）
    high_rated_classic = sum(
        1 for it in items
        if extract_year(it.get("info", ""))
        and int(extract_year(it.get("info", ""))) < 2000
        and (parse_rating(it.get("rating", "")) or 0) >= 4
    )
    low_rated_classic = sum(
        1 for it in items
        if extract_year(it.get("info", ""))
        and int(extract_year(it.get("info", ""))) < 2000
        and (parse_rating(it.get("rating", "")) or 0) <= 2
    )

    return {
        "release_year_count": n,
        "median_release_year": median_year,
        "release_year_q1": q1,
        "release_year_q3": q3,
        "release_year_spread": spread,
        "pct_pre_2000": pct_pre_2000,
        "pct_post_2015": pct_post_2015,
        "pct_classic_20y": pct_classic,
        "era_label": era_label,
        "high_rated_classic": high_rated_classic,
        "low_rated_classic": low_rated_classic,
        "classic_approval_rate": round(
            high_rated_classic / (high_rated_classic + low_rated_classic), 2
        ) if (high_rated_classic + low_rated_classic) > 0 else None,
    }


# ── 重复标记检测 ──────────────────────────────────────────────────

def normalize_title(t: str) -> str:
    """去除标题中的年份、括号内容、空格等，保留核心标题。"""
    # 去除 / 后面的副标题
    t = re.split(r"\s*/\s*", t)[0]
    # 去除括号内容
    t = re.sub(r"[\(（].*?[\)）]", "", t)
    # 去除末尾的年份
    t = re.sub(r"\s*\d{4}\s*$", "", t)
    # 去除空格和标点
    t = re.sub(r"[\s:：·\-_.]+", "", t)
    return t.lower()


def detect_duplicate_entries(items: list[dict]) -> list[dict]:
    """检测同一列表内的重复标记（可能是不同版本）。"""
    normalized = {}
    duplicates = []

    for it in items:
        title = it.get("title", "")
        if not title:
            continue
        norm = normalize_title(title)
        if not norm:
            continue

        if norm in normalized:
            existing = normalized[norm]
            duplicates.append({
                "titles": [existing["title"], title],
                "norm_key": norm,
                "ratings": [existing.get("rating", ""), it.get("rating", "")],
                "dates": [existing.get("date", ""), it.get("date", "")],
            })
        else:
            normalized[norm] = it

    return duplicates[:30]


def cross_category_duplicates(movies: list[dict], books: list[dict]) -> list[dict]:
    """检测跨品类（电影 vs 图书）的同名作品。

    用途：书影双收、原著党、跨媒体兴趣分析。
    """
    movie_index: dict[str, list[dict]] = {}
    for it in movies:
        title = it.get("title", "")
        if not title:
            continue
        norm = normalize_title(title)
        if norm:
            movie_index.setdefault(norm, []).append(it)

    results = []
    seen_norms = set()
    for it in books:
        title = it.get("title", "")
        if not title:
            continue
        norm = normalize_title(title)
        if not norm or norm in seen_norms:
            continue

        if norm in movie_index:
            seen_norms.add(norm)
            movie_items = movie_index[norm]
            results.append({
                "norm_key": norm,
                "movie_titles": [m["title"] for m in movie_items],
                "book_title": title,
                "movie_ratings": [m.get("rating", "") for m in movie_items],
                "book_rating": it.get("rating", ""),
                "movie_dates": [m.get("date", "") for m in movie_items],
                "book_date": it.get("date", ""),
            })

    return results[:30]


# ── 统计分析 ──────────────────────────────────────────────────

def rating_distribution(items: list[dict]) -> dict:
    """评分分布 → {"1": count, "2": count, ...}"""
    dist = Counter()
    for it in items:
        r = parse_rating(it.get("rating", ""))
        if r is not None:
            dist[r] += 1
    return {str(k): dist[k] for k in range(1, 6)}


def average_rating(items: list[dict]) -> float | None:
    ratings = [parse_rating(it.get("rating", "")) for it in items]
    ratings = [r for r in ratings if r is not None]
    return round(sum(ratings) / len(ratings), 2) if ratings else None


def yearly_breakdown(items: list[dict], bulk_dates: set = None) -> dict:
    """按年份统计数量和平均评分。如有 bulk_dates 则同时输出过滤后数据。"""
    years: dict[str, list[int]] = defaultdict(list)
    years_filtered: dict[str, list[int]] = defaultdict(list)
    for it in items:
        dt = parse_date(it.get("date", ""))
        if dt:
            r = parse_rating(it.get("rating", ""))
            y = str(dt.year)
            years[y].append(r)
            if bulk_dates and it.get("date", "") not in bulk_dates:
                years_filtered[y].append(r)
            elif not bulk_dates:
                years_filtered[y].append(r)

    result = {}
    for y in sorted(years.keys()):
        ratings = [r for r in years[y] if r is not None]
        entry = {
            "count": len(years[y]),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        }
        # 过滤后数据
        fr = [r for r in years_filtered.get(y, []) if r is not None]
        entry["organic_count"] = len(years_filtered.get(y, []))
        entry["organic_avg"] = round(sum(fr) / len(fr), 2) if fr else None
        result[y] = entry
    return result


def monthly_breakdown(items: list[dict], bulk_dates: set = None) -> dict:
    """按月统计数量。如有 bulk_dates 则同时输出过滤后数据。"""
    months = Counter()
    months_filtered = Counter()
    for it in items:
        dt = parse_date(it.get("date", ""))
        if dt:
            months[dt.month] += 1
            if bulk_dates and it.get("date", "") not in bulk_dates:
                months_filtered[dt.month] += 1
            elif not bulk_dates:
                months_filtered[dt.month] += 1
    result = {}
    for m in range(1, 13):
        if months[m]:
            result[MONTH_NAMES_ZH[m]] = {
                "count": months[m],
                "organic_count": months_filtered.get(m, 0),
            }
    return result


def detect_turning_points(yearly_data: dict, retroactive: dict = None, max_points: int = 3) -> list[dict]:
    """检测品味演化中的转捩点。

    算法：
    1. 从 yearly_breakdown 提取每年的 organic_avg 和 organic_count
    2. 计算评分和数量的逐年差分
    3. 差分绝对值超过 1σ 的年份标记为转捩点
    4. 综合评分差分和数量差分排序，返回 top N

    参数：
        yearly_data: yearly_breakdown() 的输出
        retroactive: retroactive_analysis() 的输出（可选，用于标注补标期）
        max_points: 最多返回几个转捩点
    """
    years = sorted(yearly_data.keys())
    if len(years) < 3:
        return []

    # 提取时序数据（优先用 organic）
    avgs = []
    counts = []
    valid_years = []
    for y in years:
        d = yearly_data[y]
        avg = d.get("organic_avg") or d.get("avg_rating")
        cnt = d.get("organic_count", 0) or d.get("count", 0)
        if avg is not None and cnt >= 3:  # 至少 3 条才纳入
            avgs.append(avg)
            counts.append(cnt)
            valid_years.append(y)

    if len(valid_years) < 3:
        return []

    # 计算差分
    rating_diffs = [avgs[i] - avgs[i - 1] for i in range(1, len(avgs))]
    count_diffs = [counts[i] - counts[i - 1] for i in range(1, len(counts))]

    # 标准差
    def std(vals):
        if len(vals) < 2:
            return 0
        mean = sum(vals) / len(vals)
        return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

    rating_std = std(rating_diffs)
    count_std = std(count_diffs)

    # 补标期年份集合
    retro_years = set()
    if retroactive and retroactive.get("retroactive_months"):
        # retroactive 没有直接的年份信息，但可以从 organic_start 推断
        organic_start = retroactive.get("organic_start", "")
        if organic_start:
            try:
                start_year = int(organic_start[:4])
                retro_years = {y for y in valid_years if int(y) < start_year}
            except (ValueError, TypeError):
                pass

    # 检测转捩点
    points = []
    for i in range(1, len(valid_years)):
        year = valid_years[i]
        r_diff = rating_diffs[i - 1]
        c_diff = count_diffs[i - 1]

        r_sig = abs(r_diff) > rating_std * 1.0 if rating_std > 0 else False
        c_sig = abs(c_diff) > count_std * 1.0 if count_std > 0 else False

        if r_sig or c_sig:
            # 综合显著性得分
            score = 0
            if rating_std > 0:
                score += abs(r_diff) / rating_std
            if count_std > 0:
                score += abs(c_diff) / count_std

            # 推断变化方向
            if r_sig and c_sig:
                change_type = "rating_and_volume"
            elif r_sig:
                change_type = "rating_shift"
            else:
                change_type = "volume_shift"

            is_retro = year in retro_years

            points.append({
                "year": year,
                "rating_before": round(avgs[i - 1], 2),
                "rating_after": round(avgs[i], 2),
                "rating_diff": round(r_diff, 2),
                "count_before": counts[i - 1],
                "count_after": counts[i],
                "count_diff": c_diff,
                "change_type": change_type,
                "significance": round(score, 2),
                "is_retroactive": is_retro,
            })

    # 按显著性排序，取 top N
    points.sort(key=lambda x: -x["significance"])
    return points[:max_points]


def day_of_week_rhythm(items: list[dict], bulk_dates: set = None) -> dict:
    """星期分布：每天的数量和平均评分。
    如有 bulk_dates，同时输出过滤后的'有机'节奏。"""
    days: dict[int, list[int]] = defaultdict(list)
    days_filtered: dict[int, list[int]] = defaultdict(list)
    for it in items:
        dt = parse_date(it.get("date", ""))
        if dt:
            r = parse_rating(it.get("rating", ""))
            wd = dt.weekday()
            days[wd].append(r)
            if bulk_dates and it.get("date", "") not in bulk_dates:
                days_filtered[wd].append(r)
            elif not bulk_dates:
                days_filtered[wd].append(r)

    result = {}
    for d in range(7):
        ratings = [r for r in days[d] if r is not None]
        fr = [r for r in days_filtered.get(d, []) if r is not None]
        result[DAY_NAMES_ZH[d]] = {
            "count": len(days[d]),
            "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "organic_count": len(days_filtered.get(d, [])),
            "organic_avg": round(sum(fr) / len(fr), 2) if fr else None,
        }
    return result


def country_breakdown(items: list[dict]) -> dict:
    """国别/地区分布。"""
    countries = Counter()
    for it in items:
        c = extract_country(it.get("info", ""))
        if c:
            countries[c] += 1
    return dict(countries.most_common(20))


def top_rated(items: list[dict], n: int = 30, min_rating: int = 4) -> list[dict]:
    """取评分最高的 n 条。"""
    rated = [(it, parse_rating(it.get("rating", ""))) for it in items]
    rated = [(it, r) for it, r in rated if r is not None and r >= min_rating]
    rated.sort(key=lambda x: (-x[1], x[0].get("date", "")))
    return [
        {
            "title": it.get("title", ""),
            "rating": r,
            "date": it.get("date", ""),
            "info": it.get("info", "")[:200],
            "comment": it.get("comment", ""),
        }
        for it, r in rated[:n]
    ]


def top_favorites(items: list[dict], n: int = 10) -> list[dict]:
    """用户的绝对十佳——5 星优先，有评论优先，保留完整信息。

    这是用户最珍视的作品，应在报告中给予最大比重。
    """
    rated = [(it, parse_rating(it.get("rating", ""))) for it in items]
    rated = [(it, r) for it, r in rated if r is not None]
    # 排序权重：评分降序 → 有评论优先 → 日期降序
    rated.sort(key=lambda x: (
        -x[1],
        0 if x[0].get("comment") else 1,
        x[0].get("date", ""),
    ), reverse=False)
    # 重新排序：评分降序，有评论优先，日期降序
    rated.sort(key=lambda x: (-x[1], 0 if x[0].get("comment") else 1))
    return [
        {
            "title": it.get("title", ""),
            "rating": r,
            "date": it.get("date", ""),
            "info": it.get("info", ""),
            "comment": it.get("comment", ""),
        }
        for it, r in rated[:n]
    ]


def bottom_rated(items: list[dict], n: int = 15, max_rating: int = 2) -> list[dict]:
    """取评分最低的 n 条。"""
    rated = [(it, parse_rating(it.get("rating", ""))) for it in items]
    rated = [(it, r) for it, r in rated if r is not None and r <= max_rating]
    rated.sort(key=lambda x: (x[1], x[0].get("date", "")))
    return [
        {
            "title": it.get("title", ""),
            "rating": r,
            "date": it.get("date", ""),
            "info": it.get("info", "")[:200],
            "comment": it.get("comment", ""),
        }
        for it, r in rated[:n]
    ]


def sample_items(items: list[dict], n: int = MAX_SAMPLES) -> list[dict]:
    """智能采样：优先选有评论的、高分/低分的，确保时间覆盖。"""
    if len(items) <= n:
        return [
            {"title": it.get("title", ""), "rating": it.get("rating", ""),
             "date": it.get("date", ""), "info": it.get("info", "")[:150],
             "comment": it.get("comment", "")}
            for it in items
        ]

    # 分层采样：按年份分组，每年均匀取
    by_year: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        dt = parse_date(it.get("date", ""))
        y = str(dt.year) if dt else "unknown"
        by_year[y].append(it)

    per_year = max(1, n // max(len(by_year), 1))
    sampled = []
    for y in sorted(by_year.keys()):
        group = by_year[y]
        # 优先有评论的
        with_comment = [it for it in group if it.get("comment")]
        take = with_comment[:per_year] if with_comment else group[:per_year]
        for it in take:
            sampled.append({
                "title": it.get("title", ""), "rating": it.get("rating", ""),
                "date": it.get("date", ""), "info": it.get("info", "")[:150],
                "comment": it.get("comment", ""),
            })

    # 如果还不够，补充无评论的
    remaining = n - len(sampled)
    if remaining > 0:
        seen_titles = {s["title"] for s in sampled}
        for it in items:
            if it.get("title", "") not in seen_titles:
                sampled.append({
                    "title": it.get("title", ""), "rating": it.get("rating", ""),
                    "date": it.get("date", ""), "info": it.get("info", "")[:150],
                    "comment": it.get("comment", ""),
                })
                seen_titles.add(it.get("title", ""))
                remaining -= 1
                if remaining <= 0:
                    break

    return sampled[:n]


# ── 品味演化 ──────────────────────────────────────────────────

def taste_evolution(items: list[dict]) -> list[dict]:
    """按年分析兴趣迁移：每年的高频关键词和偏好变化。"""
    by_year: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        dt = parse_date(it.get("date", ""))
        if dt:
            by_year[str(dt.year)].append(it)

    evolution = []
    for year in sorted(by_year.keys()):
        group = by_year[year]
        if len(group) < 3:
            continue

        # 提取关键词和类型
        words = Counter()
        countries = Counter()
        genres = Counter()
        for it in group:
            info = it.get("info", "")
            comment = it.get("comment", "")
            words.update(tokenize_zh(comment))  # 从评论提取关键词
            # 从 info 提取类型/国别作为品味信号（评论少时仍能追踪品味变化）
            for g in extract_genres(info):
                words[g] += 2  # 类型词权重加倍，因为是明确的品味标签
            c = extract_country(info)
            if c:
                countries[c] += 1
                words[c] += 1  # 国别也作为品味关键词
            for g in extract_genres(info):
                genres[g] += 1

        # 评分分布
        ratings = [parse_rating(it.get("rating", "")) for it in group]
        ratings = [r for r in ratings if r is not None]
        avg = round(sum(ratings) / len(ratings), 2) if ratings else None

        evolution.append({
            "year": year,
            "count": len(group),
            "avg_rating": avg,
            "keywords": [w for w, _ in words.most_common(20)],
            "countries": dict(countries.most_common(5)),
            "genres": dict(genres.most_common(5)),
            "sample_titles": [it.get("title", "") for it in group[:8]],
        })

    return evolution


# ── 高分作品隐藏关联 ──────────────────────────────────────────

def genre_breakdown(items: list[dict]) -> dict:
    """电影类型分布。"""
    genres = Counter()
    for it in items:
        for g in extract_genres(it.get("info", "")):
            genres[g] += 1
    return dict(genres.most_common(15))


# ── 高分作品隐藏关联 ──────────────────────────────────────────

def hidden_patterns(items: list[dict]) -> dict:
    """分析高分作品（≥4 星）的共性特征。"""
    high_rated = [it for it in items if (
        parse_rating(it.get("rating", "")) or 0) >= 4]

    # 关键词频率（只从评论提取）
    comment_words = Counter()
    genre_words = Counter()
    for it in high_rated:
        comment_words.update(tokenize_zh(it.get("comment", "")))
        for g in extract_genres(it.get("info", "")):
            genre_words[g] += 1

    # 创作者频率
    creators = Counter()
    for it in high_rated:
        creator = extract_director_or_author(it.get("info", ""))
        if creator and len(creator) >= 2:
            creators[creator] += 1

    # 国家频率
    country_counts = Counter()
    for it in high_rated:
        c = extract_country(it.get("info", ""))
        if c:
            country_counts[c] += 1

    return {
        "total_high_rated": len(high_rated),
        "comment_keywords": [w for w, _ in comment_words.most_common(25)],
        "genre_distribution": dict(genre_words.most_common(15)),
        "frequent_creators": dict(creators.most_common(15)),
        "country_distribution": dict(country_counts.most_common(10)),
        "samples": [
            {"title": it.get("title", ""), "rating": it.get("rating", ""),
             "comment": it.get("comment", "")}
            for it in high_rated[:30]
        ],
    }


# ── 遗憾清单 ──────────────────────────────────────────────────

def regret_list(wish_items: list[dict]) -> list[dict]:
    """找出 wish 列表中标记超过 2 年仍未看的条目。"""
    now = datetime.now()
    regrets = []
    for it in wish_items:
        dt = parse_date(it.get("date", ""))
        if not dt:
            continue
        days = (now - dt).days
        if days > 730:  # 超过 2 年
            regrets.append({
                "title": it.get("title", ""),
                "wish_date": it.get("date", ""),
                "days_pending": days,
                "info": it.get("info", "")[:150],
            })

    regrets.sort(key=lambda x: -x["days_pending"])
    return regrets[:50]


# ── 跨媒体联想 ────────────────────────────────────────────────

def cross_media(movies: list[dict], books: list[dict]) -> dict:
    """分析电影与图书之间的关联。"""
    # 标题交集（可能同名改编）
    movie_titles = {it["title"] for it in movies if it.get("title")}
    book_titles = {it["title"] for it in books if it.get("title")}
    overlap = movie_titles & book_titles

    # 高频关键词对比
    movie_kw = Counter()
    book_kw = Counter()
    for it in movies:
        if (parse_rating(it.get("rating", "")) or 0) >= 4:
            movie_kw.update(tokenize_zh(it.get("info", "")))
            movie_kw.update(tokenize_zh(it.get("comment", "")))
    for it in books:
        if (parse_rating(it.get("rating", "")) or 0) >= 4:
            book_kw.update(tokenize_zh(it.get("info", "")))
            book_kw.update(tokenize_zh(it.get("comment", "")))

    shared_keywords = set(dict(movie_kw.most_common(50)).keys()) & \
        set(dict(book_kw.most_common(50)).keys())

    return {
        "title_overlaps": list(overlap)[:20],
        "shared_themes": list(shared_keywords)[:20],
        "movie_top_keywords": [w for w, _ in movie_kw.most_common(20)],
        "book_top_keywords": [w for w, _ in book_kw.most_common(20)],
    }


# ── 社交卡片数据 ──────────────────────────────────────────────

def social_card_data(user_id: str, data: dict, raw: dict) -> dict:
    """汇总社交卡片所需的展示数据（含可视化所需结构）。"""
    card = {"user_id": user_id}

    for dtype in ALL_TYPES:
        collected = raw.get(dtype, {}).get("collected", [])
        type_label = TYPE_LABELS[dtype]
        unit = TYPE_UNITS[dtype]

        if not collected:
            continue

        # 检测批量标记日
        bulk_info = detect_bulk_marking(collected)
        bulk_dates = bulk_info["bulk_dates"]

        rated = [it for it in collected if parse_rating(
            it.get("rating", "")) is not None]
        avg = average_rating(collected)
        tr = top_rated(collected, n=5, min_rating=4)
        yb = yearly_breakdown(collected, bulk_dates)
        mb = monthly_breakdown(collected, bulk_dates)
        cb = country_breakdown(collected)
        gb = genre_breakdown(collected)
        dow = day_of_week_rhythm(collected, bulk_dates)
        rd = rating_distribution(collected)
        hp = hidden_patterns(collected)

        peak_year = max(
            yb.items(), key=lambda x: x[1]["organic_count"]) if yb else None
        # monthly_breakdown now returns dicts, need to handle peak_month
        peak_month = max(
            mb.items(), key=lambda x: x[1]["organic_count"]) if mb else None

        # 年度趋势（用于折线图，使用过滤后数据）
        yearly_trend = [
            {"year": y, "count": v["organic_count"],
             "avg_rating": v["organic_avg"]}
            for y, v in sorted(yb.items())
        ]

        # 国别占比 top 8
        total_country = sum(cb.values()) or 1
        country_top = [
            {"name": k, "count": v, "pct": round(v / total_country * 100, 1)}
            for k, v in list(cb.items())[:8]
        ]

        # 类型占比 top 8（电影）
        total_genre = sum(gb.values()) or 1
        genre_top = [
            {"name": k, "count": v, "pct": round(v / total_genre * 100, 1)}
            for k, v in list(gb.items())[:8]
        ]

        # 评分分布（百分比）
        total_rated = sum(rd.values()) or 1
        rating_dist = [
            {"stars": s, "count": rd[s], "pct": round(
                rd[s] / total_rated * 100, 1)}
            for s in ["5", "4", "3", "2", "1"]
        ]

        # top creators
        creators = [
            {"name": k, "count": v}
            for k, v in list(hp.get("frequent_creators", {}).items())[:6]
            if not re.match(r"https?://", k) and not re.match(r"www\.", k)
            and len(k) >= 2 and "编译局" not in k
        ]

        card[dtype] = {
            "type_label": type_label,
            "unit": unit,
            "total": len(collected),
            "avg_rating": avg,
            "top5": tr[:5],
            "peak_year": {"year": peak_year[0], "count": peak_year[1]["organic_count"]} if peak_year else None,
            "peak_month": {"month": peak_month[0], "count": peak_month[1]["organic_count"]} if peak_month else None,
            "yearly_trend": yearly_trend,
            "country_top": country_top,
            "genre_top": genre_top,
            "rating_distribution": rating_dist,
            "rating_dist_raw": rd,
            "creators_top": creators,
            "day_of_week": dow,
            "bulk_marking": {
                "threshold": bulk_info["threshold"],
                "bulk_days": bulk_info["bulk_days"],
                "bulk_items": bulk_info["bulk_items"],
                "bulk_pct": bulk_info["bulk_pct"],
            },
            "high_rated_count": hp.get("total_high_rated", 0),
            "top_keywords": hp.get("comment_keywords", [])[:10],
        }

    return card


# ── 完整分析 ──────────────────────────────────────────────────

def analyze_category(items: list[dict], wish_items: list[dict], dtype: str) -> dict:
    """分析单个类别（movie/book/music）的 collected + wish。"""
    type_label = TYPE_LABELS.get(dtype, dtype)
    result = {
        "type_label": type_label,
        "collected_count": len(items),
        "wish_count": len(wish_items),
    }

    # 音乐数据稀疏处理
    is_sparse = dtype == "music" and len(items) < MUSIC_SPARSE_THRESHOLD
    if is_sparse:
        result["sparse"] = True
        result["sparse_note"] = f"音乐标记仅 {len(items)} 条（阈值 {MUSIC_SPARSE_THRESHOLD}），跳过深度分析"

    if items:
        # 检测批量标记日
        bulk_info = detect_bulk_marking(items)
        bulk_dates = bulk_info["bulk_dates"]
        result["bulk_marking"] = {
            "threshold": bulk_info["threshold"],
            "bulk_days": bulk_info["bulk_days"],
            "bulk_items": bulk_info["bulk_items"],
            "bulk_pct": bulk_info["bulk_pct"],
            "top_bulk_days": bulk_info["top_bulk_days"],
        }

        result["rating_distribution"] = rating_distribution(items)
        result["avg_rating"] = average_rating(items)
        result["retroactive"] = retroactive_analysis(items)
        result["yearly_breakdown"] = yearly_breakdown(items, bulk_dates)
        result["monthly_breakdown"] = monthly_breakdown(items, bulk_dates)
        result["turning_points"] = detect_turning_points(
            result["yearly_breakdown"], result["retroactive"]
        )
        result["day_of_week_rhythm"] = day_of_week_rhythm(items, bulk_dates)
        result["country_breakdown"] = country_breakdown(items)
        result["genre_breakdown"] = genre_breakdown(items)
        result["top_rated"] = top_rated(items)
        result["top_favorites"] = top_favorites(items)
        result["bottom_rated"] = bottom_rated(items)
        result["taste_evolution"] = taste_evolution(items)
        result["hidden_patterns"] = hidden_patterns(items)
        result["samples"] = sample_items(items)

        # ── 新增维度分析（音乐稀疏时跳过） ──
        if not is_sparse:
            result["comment_sentiment"] = comment_sentiment(items)
            result["top_rated_genre_bias"] = top_rated_genre_bias(items)
            result["abstraction_index"] = abstraction_index(
                items, result["taste_evolution"], result["country_breakdown"]
            )
            result["era_orientation"] = era_orientation(items)
        result["duplicates"] = detect_duplicate_entries(items)

    if wish_items:
        result["regret_list"] = regret_list(wish_items)
        result["wish_samples"] = sample_items(wish_items, n=80)

    return result


def full_analysis(user_id: str, csv_dir: Path) -> dict:
    """运行完整分析，返回结果字典。"""
    data: dict = {dtype: {} for dtype in ALL_TYPES}
    raw: dict = {dtype: {"collected": [], "wish": []} for dtype in ALL_TYPES}

    for (dtype, cat), suffix in FILE_MAP.items():
        path = csv_dir / f"{user_id}_{suffix}.csv"
        items = load_csv(path)
        raw[dtype][cat] = items
        print(f"  读取 {path.name}: {len(items)} 条")

    # 逐类别分析
    for dtype in ALL_TYPES:
        collected = raw[dtype]["collected"]
        wish = raw[dtype]["wish"]
        if collected or wish:
            data[dtype] = analyze_category(collected, wish, dtype)

    # 跨媒体分析
    if raw["movie"]["collected"] and raw["book"]["collected"]:
        data["cross_media"] = cross_media(
            raw["movie"]["collected"], raw["book"]["collected"]
        )

    # 跨品类重复检测（书影双收）
    if raw["movie"]["collected"] and raw["book"]["collected"]:
        cross_dups = cross_category_duplicates(
            raw["movie"]["collected"], raw["book"]["collected"]
        )
        if cross_dups:
            data["cross_category_duplicates"] = cross_dups

    # 社交卡片数据
    data["social_card"] = social_card_data(user_id, data, raw)

    # 已标记标题列表（供推荐去重）
    marked_titles = {"collected": set(), "wish": set()}
    for dtype in ALL_TYPES:
        for it in raw[dtype]["collected"]:
            t = it.get("title", "").strip()
            if t:
                marked_titles["collected"].add(t)
        for it in raw[dtype]["wish"]:
            t = it.get("title", "").strip()
            if t:
                marked_titles["wish"].add(t)
    data["marked_titles"] = {
        "collected": sorted(marked_titles["collected"]),
        "wish": sorted(marked_titles["wish"]),
    }

    return data


# ── 入口 ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="豆瓣数据分析器 — 从导出 CSV 生成分析 JSON"
    )
    parser.add_argument("user", help="豆瓣用户 ID")
    parser.add_argument("--dir", default=".",
                        help="CSV 文件目录（默认当前目录）")
    parser.add_argument("--output", "-o", default=None,
                        help="输出 JSON 路径（默认: <user>_analysis.json）")
    args = parser.parse_args()

    csv_dir = Path(args.dir)
    if not csv_dir.exists():
        print(f"[错误] 目录不存在: {csv_dir}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else csv_dir / \
        f"{args.user}_analysis.json"

    print(f"[*] 分析用户 {args.user} 的豆瓣数据...\n")
    result = full_analysis(args.user, csv_dir)
    result["user_id"] = args.user
    result["analysis_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"\n[完成] 分析结果已保存到: {output_path}")
    for dtype in ALL_TYPES:
        d = result.get(dtype, {})
        if d.get("collected_count"):
            label = d["type_label"]
            unit = TYPE_UNITS[dtype]
            sparse_note = " (数据稀疏，跳过深度分析)" if d.get("sparse") else ""
            print(f"  {label}: {d['collected_count']} {unit}已记录, "
                  f"{d.get('wish_count', 0)} {unit}待听/看/读{sparse_note}")
    if "cross_media" in result:
        cm = result["cross_media"]
        if cm.get("title_overlaps"):
            print(f"  跨媒体: 发现 {len(cm['title_overlaps'])} 个同名作品")


if __name__ == "__main__":
    main()
