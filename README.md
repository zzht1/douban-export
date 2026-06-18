# 豆瓣记录导出 + 智能分析

豆瓣书影音数据的完整工作流：**导出 → 分析 → 报告 → 卡片**。

## 当前状态

- CLI 导出与 `analyzer.py` 核心分析已成型，支持电影、图书、音乐三类数据。
- Flask Web 原型已可提交豆瓣用户、后台爬取/分析、生成报告与社交卡片。
- MBTI 训练数据管线已有种子采集、特征构建、模型训练和 Web 端预测器。
- 本地调试脚本不应写死真实 Cookie；如需联网测试，使用 `.env` 或环境变量 `DOUBAN_COOKIE`。

## 功能概览

| 模块 | 文件 | 功能 |
|------|------|------|
| **导出** | `douban_movie_export.py` | 将豆瓣用户的电影/图书/音乐列表导出为 CSV 和 Markdown |
| **分析** | `analyzer.py` | 读取 CSV，生成结构化分析 JSON（统计、节奏、演化、关联等） |
| **报告** | Skill: `douban-insight` | 基于 JSON 生成深度自我镜像报告 + 社交卡片 |
| **Web** | `web/app.py` | 提供输入页、任务进度、报告页和下载接口 |
| **MBTI 训练** | `collect_mbti_seeds.py` / `build_mbti_dataset.py` / `train_mbti_model.py` | 采集自报 MBTI 用户、构建训练集并训练预测模型 |

## 一、数据导出

```bash
python douban_movie_export.py <用户名> [--cookie "cookie字符串"] [--type movie|book|music|all]
```

| 参数 | 说明 |
|------|------|
| `<用户名>` | 豆瓣用户 ID（URL 中 `/people/` 后面的部分） |
| `--cookie` | 可选，浏览器 Cookie 字符串，绕过访问限制 |
| `--type` | `movie`=仅电影, `book`=仅图书, `music`=仅音乐, `all`=全部（默认） |

**输出文件：**

| 文件 | 内容 |
|------|------|
| `{用户名}_movies.csv / .md` | 已看电影 |
| `{用户名}_movie_wish.csv / .md` | 想看电影 |
| `{用户名}_books.csv / .md` | 已读图书 |
| `{用户名}_book_wish.csv / .md` | 想读图书 |
| `{用户名}_music.csv / .md` | 已听音乐 |
| `{用户名}_music_wish.csv / .md` | 想听音乐 |

**导出字段：** 名称 / 评分 / 日期 / 简介（作者·译者·出版年） / 短评 / 封面 / 豆瓣链接

## 二、数据分析

```bash
python analyzer.py <用户ID> [--dir CSV目录] [--output 输出JSON路径]
```

读取导出的 CSV 文件，生成 `<用户ID>_analysis.json`，包含：

| 分析维度 | 说明 |
|----------|------|
| **基础统计** | 总量、评分分布（1-5星）、均分 |
| **年度/月度趋势** | 按年/月分段的标记量与均分 |
| **一周节奏** | 星期一至周日的标记量与评分偏好（过滤批量标记日） |
| **国别分布** | 电影/图书的来源国 Top 分布 |
| **品味演化** | 按年分段的关键词、国家变化、代表作品 |
| **批量标记检测** | 识别集中整理的日期（阈值 = max(p90, 8)），区分有机数据与批量数据 |
| **遗憾清单** | 想读/想看列表中年代久远的条目 |
| **跨媒体关联** | 电影与图书的标题重叠、主题交叉、关键词对比 |
| **隐藏模式** | 高分作品的信息关键词、评论关键词、高频创作者 |
| **用户评论样本** | 用户亲笔短评（用于报告引用） |
| **已标记标题** | 完整的已看/想看/已读/想读列表（用于推荐去重） |

**批量标记过滤：** analyzer 会自动检测单日标记量异常高的日期（通常是用户在集中整理而非实时标记），将其从节奏分析中过滤，输出 `organic_count` 和 `organic_avg` 以反映真实的观影/阅读行为。

## 三、报告 + 卡片

通过 Qoder Skill `douban-insight` 触发，基于分析 JSON 生成：

### 深度报告 (`<用户ID>_report.md`)

不是数据摘要，而是**自我镜像**——帮助用户认识自己是什么样的人：

- **书影音 MBTI** — T-R-A-C 四维模型（思维向/漫游型/作者向/审慎型）+ 真实 MBTI 推测
- **你如何思考** — 从亲笔评论中揭示认知风格
- **你的核心执念** — 贯穿所有选择的主题
- **你的矛盾** — 品味中的张力及其成因
- **你的来路** — 品味演化作为智识成长史
- **你的节奏** — 过滤后的有机数据 + 情感节律
- **你应该读的** — 连接核心关切、严格去重后的推荐
- **你的未完成** — 遗憾清单作为自我许诺

### 社交卡片 (`<用户ID>_card.html` + `.png`)

纯 CSS 实现的可视化长图卡片，深色主题，适合手机分享：

- 核心数据（观影/阅读量、评分率）
- 书影音 MBTI 类型 + 真实 MBTI 推测
- 评分分布、年度趋势、国别分布
- 电影类型偏好、一周节奏
- 最爱创作者、5 星代表作
- 评论关键词云
- 一句话总结

## 完整工作流

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install -r web/requirements.txt

# 2. 导出豆瓣数据
python douban_movie_export.py <用户名> [--cookie "..."]

# 3. 运行分析器
python analyzer.py <用户名>

# 4. 在 Qoder 中使用 douban-insight 技能生成报告和卡片
```

## Web 原型

```bash
python run.py
```

默认访问 `http://127.0.0.1:5000`。Web 流程会创建后台任务，依次执行爬取、分析、MBTI 预测、报告生成和卡片生成。未配置 `LLM_API_KEY` 时会使用模板报告降级。

## MBTI 训练管线

```bash
# 可选：设置 Cookie，避免命令行历史记录泄露
$env:DOUBAN_COOKIE="你的豆瓣 Cookie"

python collect_mbti_seeds.py --max-seeds 500
python build_mbti_dataset.py --min-items 30
python train_mbti_model.py
```

批量构建训练集时会输出 `data/mbti_training/failed_users.json`，记录未完成用户、失败阶段和原因，便于人工复查。

## 安装依赖

```bash
pip install -r requirements.txt
```

- `requests` — 网络请求
- `beautifulsoup4` — HTML 解析

## Cookie 获取方法

1. 浏览器打开豆瓣并登录
2. F12 → Network → 刷新页面 → 点击任意请求
3. 复制 Request Headers 中的 `Cookie` 值

真实 Cookie 只应放在本机 `.env` 或环境变量 `DOUBAN_COOKIE` 中，不要写进测试脚本、README、提交记录或 issue。

## 注意事项

- 未提供 Cookie 时只能抓取公开数据，可能遇到 403
- 每页间隔 2-4 秒随机延迟，避免被封
- 自动按链接去重，不会输出重复条目
- 推荐作品时严格确认不在用户已标记列表中（对照 `marked_titles`）
- 节奏分析必须使用 organic 数据，过滤批量标记日
- 报告中大量引用用户自己的评论作为"镜子"
