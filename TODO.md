# douban-insight 后续工作备忘录

> 写于 2026-06-04，供明天在新窗口继续推进。

---

## 已完成

### 2026-06-17 接续状态 ✅
- Web 入口已从"远期设想"推进为本地 Flask 原型：`web/app.py` 提供首页、任务 API、状态轮询、报告页、卡片/报告下载和缓存数据删除。
- 后台任务链路已串起：`web/worker.py` 调用 `web/scraper.py` → `analyzer.full_analysis()` → `web/mbti_predictor.py` → `web/llm_report.py`。
- Web 任务链路已补缓存复用与失败追踪：24 小时内命中缓存可直接复用；爬取失败会写入 `data/<user_id>/<user_id>_failure.json`，抓取元数据写入 `data/<user_id>/<user_id>_scrape_meta.json`。
- MBTI 训练管线已具备脚本骨架：`collect_mbti_seeds.py`、`build_mbti_dataset.py`、`train_mbti_model.py`，并已有 `data/mbti_training/` 训练数据与 `web/models/` 模型文件。
- 已清理临时测试脚本中的硬编码豆瓣 Cookie；后续所有联网调试使用 `.env` 或环境变量 `DOUBAN_COOKIE`。
- 批量训练集构建必须输出失败清单：`data/mbti_training/failed_users.json`，记录用户、阶段与失败原因。

### 数据采集 ✅
- 17 个代表性用户的豆瓣数据已全部爬取（CSV 在 `result/` 目录）
- 17 个用户的 `_analysis.json` 已全部生成（在 `result/` 目录）
- 横向对比特征数据：`result/comparison_features.json`
- 批量脚本：`batch_research.py`（DATA_DIR = result/）

### 维度设计 ✅
- 确定了 4 个行为维度 → 映射真实 MBTI：
  1. **价值轴 vs 逻辑轴**（F/T）— 被什么打动：人性情感 vs 系统概念
  2. **抽象轴 vs 具象轴**（N/S）— 活在哪个世界：隐喻实验 vs 写实纪实
  3. **收敛轴 vs 开放轴**（J/P）— 如何组织生活：愿望清单比、评分率、消费节奏
  4. **经典轴 vs 新潮轴** — 与时间的关系：作品年代分布
- 用户确认：不再叫“书影音 MBTI”，产品定位是“自我镜像”
  - MBTI 推断是报告中的一个“啊哈时刻”，不是最终交付物
  - 报告结构：你的来路 → 核心执念 → 你的矛盾 → 你是谁 → 你的未完成 → 你应该看的（也可以从你的未完成里找）

### Phase 1：analyzer.py 核心算法 ✅
- **1.1 F/T 评论语义分析**：`comment_sentiment()` — F_WORDS/T_WORDS 词库 + 关键词分类，输出 F/T_score、leaning、exemplars
- **1.2 F/T top_rated 类型偏好**：`top_rated_genre_bias()` — 5 星作品 genre 分析，F/T lift、bias
- **1.3 N/S 抽象度指标**：`abstraction_index()` — 关键词跳跃性 + 文化广度(Shannon炳) + 互文引用率，综合 N_score
- **1.4 经典 vs 新潮轴**：`era_orientation()` — 发行年代中位数、IQR、pct_pre_2000/2015、era_label(TC/TN/TB)、classic_approval_rate
- **1.5 重复标记检测**：`detect_duplicate_entries()` — 标题归一化后检测重复，输出标题、评分、日期
- **1.6 跨品类重复检测**：`cross_category_duplicates()` — 检测书影双收（同一作品同时标记了电影和图书）
  - `normalize_title()` 已提取为顶层函数，供 intra/cross 两个函数复用
  - 已集成到 `full_analysis()`，输出 `cross_category_duplicates` 字段
  - 17 人验证：shunian=27组、tjz230=25组、Sacronlau=30组、171133816=19组
  - **价值信号**：书影双收说明用户对该作品/主题有深度兴趣，可服务于未来推荐系统
  - `compare_users.py` 表 9 已扩展，含跨品类重复数量和示例
- **1.5 补标检测**：`retroactive_analysis()` 已保留作为可视化辅助数据（主信号仍为 `detect_bulk_marking`）
- 全部新函数已集成到 `analyze_category()`，17 人数据已重新生成

### Phase 2：skill.md 重写 ✅
- 新增 MBTI 推断算法指令（基于 4 个结构化字段）
- F/T 维度：评论语义(60%) + 类型偏好(40%) 加权
- N/S 维度：直接读取 abstraction_index.leaning，辅助 cultural_breadth、intertextual_rate
- J/P 维度：wish_ratio + 评分集中度 + bulk_pct 综合判断
- INFJ vs INTP 区分逻辑已写入
- 报告结构已重写为六板块递进式
- 数据呈现注意事项：最爱栏目表述、沉默的大多数、重复标记

### 早期代码改动 ✅
- `analyzer.py`：新增 `retroactive_analysis()` 函数（补标洪水检测，基于年代 lag）
- `skill.md`：新增德尔菲神谕 Γνῶθι σεαυτόν（认识你自己）作为 HTML 卡片开头铭文
- `compare_users.py`：横向对比脚本，已扩展为 9 张对比表（含 F/T、N/S、经典/新潮、重复标记）

---

## 待做（按优先级排序）

### Phase 2.5：报告质量打磨 ✅

> 来源：copy.md 用户反馈（2026-06-04），Phase 1/2 未覆盖的独立问题

- [x] **最爱栏目表述**：skill.md 已加入"有力论证"指令——引用评论、连接核心执念、对比同类评分；无法论证则不设栏目
- [x] **沉默的大多数**：skill.md 已加入评分覆盖率呈现 + 沉默解读（选择性表达 vs 行为模式）+ 书影评分率对比
- [x] **重复标记在报告中呈现**：skill.md 已加入 intra-category 重复 + cross-category 书影双收的呈现指令，JSON 结构已补上 `cross_category_duplicates` 字段

### Phase 3：交互式时间轴（"时间旅行"） ✅ 算法已完成

> 来源：CinePersona（影格）的"时间旅行"功能

- [x] **转捩点检测算法**：`detect_turning_points()` — 逐年差分超过 1σ 标记为转折点
  - 支持评分突变（`rating_shift`）、数量突变（`volume_shift`）、双重变化（`rating_and_volume`）
  - 结合 `retroactive` 数据标注补标期转捩点（`is_retroactive=true`）
  - 已集成到 `analyze_category()`，输出 `turning_points` 字段
  - 17 人验证：cabaret=[2012,2016,2018]、tjz230=[2006,2007,2023]、shunian=[2024,2013,2021]
- [x] skill.md 已更新：JSON 结构新增 `turning_points`，"你的来路"板块新增转捩点解读指令
- [ ] **CSS 时间轴可视化**（待 Web 版实现）：
  - 方案 A：CSS 实现静态时间轴（竖线 + 圆点 + 标签），保持长图截图兼容
  - 方案 B：未来 Web 版用轻量 SVG 或 Chart.js

### Phase 4：音乐维度 ✅ 最小版本已完成

> 来源：Roast My Douban（唯一覆盖三类的项目）；Spotify 4维框架
> 目标：补充音乐分析，使 douban-insight 成为唯一的书+影+音统一人格框架

**最小版本 ✅：**
- [x] `douban_movie_export.py` 新增 `music` 类型（URLS/LABELS/SUFFIXES/argparse/main）
- [x] `analyzer.py` FILE_MAP 新增 music 条目，`full_analysis()` 支持三类别循环
- [x] `TYPE_LABELS`/`TYPE_UNITS`/`ALL_TYPES` 常量集中管理（替代硬编码）
- [x] 数据稀疏处理：`MUSIC_SPARSE_THRESHOLD=20`，低于阈值时跳过深度分析，标记 `sparse=True`
- [x] `social_card_data()` 支持 music
- [x] `analyze_category()` 支持 music（type_label="聆听"，unit="张"）
- [x] 17 人 JSON 已重新生成（当前无音乐 CSV，music 字段为空）

**完整版本（远期）：**
- 音乐维度的 T-R-A-C 子维度计算
- 跨媒体关联：喜欢某类电影的人倾向听什么类型的音乐
- Spotify/网易云数据导入（如果用户有）

**FILE_MAP 扩展：**
```python
FILE_MAP = {
    ("movie", "collected"): "movies",
    ("movie", "wish"):      "movie_wish",
    ("book",  "collected"): "books",
    ("book",  "wish"):      "book_wish",
    ("music", "collected"): "music",      # 新增
    ("music", "wish"):      "music_wish",  # 新增
}
```

**注意**：
- 豆瓣音乐标记量通常远少（很多人不标记音乐），需处理"数据稀疏"情况
- 音乐标记 < 20 条时降级为"你似乎不怎么标记音乐"，不强行分析
- 音乐 info 字段格式与电影/书不同，解析逻辑需单独处理

### Phase 5：Web 入口 🟡 本地原型已完成，待验证/打磨

> 来源：RateYourDouban（输入豆瓣ID即出结果，15000+报告）
> 目标：将本地 CLI 脚本封装为轻量 Web 服务，降低使用门槛

**现状**：
- 本地 Flask 原型已存在：`run.py` 启动，`web/app.py` 提供前端和 API。
- 当前完整流程：`web/scraper.py` 爬取 → `analyzer.py` 分析 → MBTI 预测 → LLM/模板报告 → 社交卡片 HTML。
- 全流程需要 Python 环境；真实爬取通常需要用户提供豆瓣 Cookie；LLM 报告需要 API Key，未配置时使用模板报告。
- 单次运行耗时 3-8 分钟（瓶颈在爬取和 LLM 生成）

**阶段一：本地可用原型（已实现，待验证）**
- [x] 用户输入豆瓣 ID 或主页链接
- [x] 可选 Cookie 输入
- [x] 后台异步任务 + 进度轮询
- [x] 生成报告 HTML 和社交卡片 HTML
- [x] 报告/卡片下载接口
- [x] 指定用户缓存数据删除接口
- [ ] 用真实 Cookie 跑一次完整端到端爬取验证
- [x] 为无 Cookie/403/空数据场景补充清晰失败记录和用户提示
- [ ] 将社交卡片导出 PNG 的链路产品化

### Phase 6：MBTI 训练管线优化 ✅ v3 已完成，全部维度提升

- [x] 本地训练链路可运行：`augment_mbti_data.py` → `train_mbti_model.py` → `test_mbti.py`
- [x] 训练/推理特征处理一致：模型导出包含 `imputer_statistics`，推理端按同一统计量填补缺失值
- [x] 训练评估不再把合成样本泄漏进测试集：`split/manifest.json` 记录真实用户划分
- [x] 采种脚本支持小范围试跑与失败落盘：`seed_progress.json` / `seed_failures.json`
- [x] 扩大真实种子样本：25 → 80 人（豆瓣反爬限制，27 人有本地数据可构建特征）
- [x] 特征提取代码去重：`mbti_features.py` 共享模块统一维护
- [x] 数据增强优化：特征统计量校准噪声、按类型稀缺度加权变体数、自适应变体数
- [x] 重新训练后批量测试验证：`test_mbti.py` 对 20 人做预测对比（v3）
  - IE: 90.0% | NS: 75.0% | FT: 85.0% | JP: 80.0%
  - ≥3 维度正确: 85.0%（v2: 68.4%）
- [x] 规则兆底已基于种子数据校准：sigmoid 阈值、FT 归一化、JP 双信号
- [x] GradientBoosting + GridSearchCV 支持已实现（真实样本 ≥50 自动切换）

### Phase 7：MBTI 样本扩容至 200 真实用户 🟡 80/200 种子，27 可用

> 当前瓶颈：25 人种子 + 335 合成样本，模型泛化能力受限（NS 63.2%，IE 73.7%）。
> 目标：200 个真实用户标注，覆盖全部 16 种 MBTI 类型，每种类型至少 8 人。

**扩容策略：**
- [ ] 豆瓣 MBTI 小组爬取：从 MBTI 自由讨论等小组抓取用户自报类型 + 书影音主页链接
- [ ] 豆瓣影评/书评用户交叉：在已知类型用户的关注列表/粉丝中发现新用户
- [ ] 外部数据源：Reddit r/mbti、Personality Database 等平台的豆瓣用户交叉标注
- [ ] 自报收集入口：在 Web 版加入告诉我你的 MBTI 可选字段，积累自报数据
- [ ] 半自动标注管线：build_mbti_candidate_pool.py 扩展 - 批量爬取 - 特征提取 - 规则预标注 - 人工复核

**质量把控：**
- [ ] 每种类型至少 8 人（当前最少的 ESTJ/ENFJ/ISFJ 仅 1 人）
- [ ] 优先补 S 类型（当前仅 6 人）和 E 类型（当前仅 3 人）
- [ ] 行为标注 vs 自报标注比例控制（行为标注需有 evidence 字段）
- [ ] 新增数据后立即重跑 test_mbti.py 验证准确率提升

**训练升级（样本达标后）：**
- [ ] 替换模型：200 真实样本 - GradientBoosting / XGBoost，对比 RF 基线
- [ ] 交叉验证超参搜索：GridSearchCV 在真实样本上做
- [ ] 降低增强比例：真实 200 + 合成 200（1:1），替代当前 1:13.4

### Phase 8：LLM 提示词优化——基于 MBTI 的深度人格洞察 🟡 阶段一已完成

> 当前问题：web/llm_report.py 的 _generate_with_llm() 仅传入原始分析 JSON，
> MBTI 预测结果（含维度置信度）未被显式注入 prompt，LLM 需自行从数据推断 MBTI，
> 导致判断浅、洞见不足。

**核心思路：让 MBTI 预测结果成为 prompt 的人格骨架，LLM 专注于用人话讲出这个人的故事。**

**阶段一：Prompt 结构升级** ✅
- [x] 将 mbti_predictor.predict_mbti() 的输出（类型 + 各维度置信度 + 判定方式）注入 prompt
  - `_template_identity()` 已改用 `predict_mbti()`，消除 ~170 行重复推断代码
  - `_build_analysis_summary()` 已注入 MBTI 预测结果（类型/置信度/方法/维度详情）
- [x] prompt 中增加人格矛盾挖掘指令：当某维度置信度低（<0.6）时，提示 LLM 重点分析该维度的矛盾信号
- [x] 增加人格光谱概念指令：system prompt 已加入"人格光谱"和"低置信度维度深度分析"指引

**阶段二：报告质量提升**
- [ ] 你是谁板块升级：从泛泛 MBTI 描述 - 结合具体作品的个性化人格画像
- [ ] 增加人格光谱概念：不是非此即彼，而是你在 I-E 光谱上的位置是...
- [ ] 引入对比框架：与同类型用户的典型差异、与该用户品味相似但类型不同的人的对比
- [ ] 评论区深度引用策略：让 LLM 选择最能体现人格特质的 3-5 条评论，做评论中的人格密码分析

**阶段三：迭代验证**
- [ ] A/B 测试：同一用户分别用旧/新 prompt 生成报告，人工对比洞见深度
- [ ] 建立报告质量评分卡：洞见密度、引用准确性、叙事流畅度、用户共鸣度
- [ ] 收集真实用户反馈：Web 版加入这份报告说得准吗反馈入口

**阶段二：按需生成**
- 用户输入豆瓣 ID → 后台异步运行爬取 + 分析 → 生成报告
- 需要队列机制（爬取有频率限制）
- 前端：输入框 + 进度条 + 结果展示
- 考虑用 Cloudflare Worker + R2 存储，成本极低

**阶段三：用户系统（远期）**
- 登录后可保存历史报告、对比不同时期
- 分享链接（类似 RateYourDouban 的 `/report/{douban_id}`）

**注意**：
- 豆瓣爬取需要 Cookie/登录态，Web 版需用户自行输入或提供代理
- LLM 调用成本：每份报告约 ¥0.5-2，免费开放需限流
- 隐私：报告包含真实书影音数据，需明确告知并获得同意

---

## 优先级总览

| 序号 | 改进项 | 预估工作量 | 状态 |
|------|--------|-----------|------|
| 1 | Phase 1 核心算法 (F/T, N/S, 经典/新潮, 重复检测) | 中 | ✅ 完成 |
| 2 | Phase 2 skill.md 重写 + MBTI 推断 | 中 | ✅ 完成 |
| 3 | Phase 1.6 跨品类重复检测（书影双收） | 小 | ✅ 完成 |
| 4 | Phase 2.5 报告质量打磨（最爱表述/沉默大多数/重复+书影双收呈现） | 小 | ✅ 完成 |
| 5 | Phase 4 音乐维度（最小版本） | 中 | ✅ 完成 |
| 6 | Phase 3 品味时间轴算法（转捩点检测） | 中 | ✅ 完成 |
| 7 | Phase 5 Web 入口（本地原型） | 大 | 🟡 待端到端验证 |
| 8 | Phase 6 MBTI 训练管线 v3 | 中 | ✅ 完成（全维度提升） |
| 9 | Phase 7 MBTI 样本扩容至 200 | 大 | 🟡 80/200（反爬受限） |
| 10 | Phase 8 LLM 提示词优化（MBTI 驱动人格洞察） | 中 | 🟡 阶段一已完成 |

**推荐顺序**：Phase 7 样本扩容 → Phase 8 提示词优化 → 跑通 Web 端到端验证 → CSS 时间轴可视化 → Web 部署方案

---

## 关键文件位置

| 文件 | 说明 |
|------|------|
| `analyzer.py` | 核心分析脚本（~1400行），含 5 个新维度分析函数 |
| `mbti_features.py` | MBTI 特征提取共享模块，统一 17 个特征的提取/合并/质检 |
| `label_candidates.py` | MBTI 标注脚本，为未标注候选用户分配标签 |
| `skill.md` | `.qoder/skills/douban-insight/skill.md`，报告生成指令 + MBTI 算法 |
| `batch_research.py` | 批量爬取脚本，DATA_DIR = result/ |
| `compare_users.py` | 横向对比脚本（9 张对比表） |
| `result/*_analysis.json` | 17 人分析数据（已含新维度） |
| `result/*_movies.csv` 等 | 17 人原始 CSV |
| `result/comparison_features.json` | 17 人特征对比数据（含 F/T、N/S、era 等） |
| `douban_movie_export.py` | 单用户导出脚本 |
| `web/mbti_predictor.py` | MBTI 混合预测器（ML + 规则兆底） |
| `web/models/mbti_model.pkl` | v2.0 训练模型（25 种子 + 335 合成） |

## 17 个调研用户速查

| 用户 | 特征 | 数据量 |
|------|------|--------|
| cabaret | 极端影迷(5033影/5书) | 大量评论 |
| xilouchen | 重度影迷(4516影/32书), 评分极严(avg 2.62) | 每部都写长评 |
| film101 | 万部影迷(4612影), 18年跨度 | 评论短(标签式) |
| Sacronlau | 重度影迷(4002影), 长评 | 评论很长(130字) |
| tjz230 | 影迷+写评(4460影), 22演化阶段 | 每部写评, 12跨媒体 |
| 171133816 | 影迷(2296影), 宽容给分 | 8跨媒体重叠 |
| 102454210 | 影迷(1646影), 大量想看 | 每部长评(107字) |
| aada | 影迷(1585影), 严格给分, 16年跨度 | 评论少而短 |
| shunian | 书影双修(1186影/2550书), 杂食 | 每部写评 |
| 156883939 | 书影均衡(811影/847书), 宽容给分 | 大量长评(200字) |
| feizhaizhangmen | 影迷(763影), 严格给分 | 评论多但短(30字) |
| 4075628 | 书虫(231影/2155书), 严格给分 | 书评多(89%) |
| fangyunan | 纯书虫(0影/1170书), 701想看 | 书评短 |
| 1087580 | 纯书虫(0影/1390书), 2300想读 | 书评长(135字) |
| zionius | 专精书虫(22影/268书), 极少评论 | 5%评论率 |
| Schopenhauer126 | 少量(89影/53书), 严格, 极少评论 | 2%评论率 |
| wzfeng2019 | 极少量(9影/14书), 全5星 | 书评长但不多 |

## 2026-06-18 接续更新 ✅

### v1 早期进展
- `collect_mbti_seeds.py` 已补失败保护：匿名登录网关立即停止，写 `seed_failures.json` / `seed_progress.json`；空运行不会覆盖已有 `seeds.json`。
- `build_mbti_dataset.py` 保留 `source_user_id`，写 `dataset_manifest.json`。
- `train_mbti_model.py` 已修正评估口径：`NS` 在测试集单类时标记为 `not_evaluable`。
- `test_mbti.py` 已跑通，当前推理结果为 `ml+rules`。
- 新增 `build_mbti_candidate_pool.py`，候选池 17 人，按 `ns_low` / `ns_boundary` 排序。

### v2 训练管线完成
- **种子扩展**: 9 → 25 人（新增 `label_candidates.py`，16 人行为标注）
- **代码重构**: 特征提取统一到 `mbti_features.py`（消除 3 处重复）
- **数据增强**: 特征统计量校准噪声 + 类型稀缺度加权（360 样本: 25 真实 + 335 合成）
- **规则校准**: `rule_based_predict()` 基于种子数据 sigmoid 阈值、FT 归一化、JP 双信号
- **混合策略**: ML 置信度 ≥ 0.6 信任模型，否则回退规则
- **批量测试**: `test_mbti.py` 对 19 人做全量预测对比
  - 维度准确率: IE 73.7% | NS 63.2% | FT 84.2% | JP 73.7%
  - ≥3 维度正确: 68.4%
- **当前瓶颈**: NS 维度仍是最弱环节（种子数据 N/S 重叠度高），需更多真实 S 样本

### v3 代码修复与训练管线优化
- **Bug 修复**:
  - `web/config.py`: `.env` 加载器类型转换修复（PORT 从 string → int）
  - `web/scraper.py`: 增量缓存功能从死代码变为实际集成到 `_scrape_task`
  - `web/llm_report.py`: 消除重复 MBTI 推断（`_template_identity` 改用 `mbti_predictor.predict_mbti()`）
- **Phase 8 初步**: LLM prompt 注入 MBTI 预测结果作为人格骨架，增加"人格光谱"概念和低置信度维度分析指令
- **训练脚本升级**:
  - `train_mbti_model.py`: 支持 GradientBoosting（真实样本 ≥50 自动切换）+ GridSearchCV 超参搜索
  - `augment_mbti_data.py`: 自适应变体数（样本越多增强比例越低，从 1:13 降至 1:2）
  - `build_mbti_dataset.py`: 分层分割替代随机分割（搜索 2000 次找最佳维度覆盖）
  - `test_mbti.py`: 新增置信度分层准确率分析
- **采集优化**: `collect_mbti_seeds.py` 自动延迟（有 Cookie 时 1-2.5s）、跳过已有种子、累计目标计数
- **种子采集**: 25 → 80 人（目标 200，豆瓣反爬触发腾讯云验证码，新种子无法继续爬取）
  - 80 种子覆盖 12 种 MBTI 类型：INFJ:18, ENTP:11, INTJ:10, INFP:10, INTP:10, ENTJ:4, ESTJ:3, ENFJ:3, ISTJ:3, ISFJ:3, ENFP:3, ISFP:2
  - 其中 27 人有本地数据可直接构建特征，其余 53 人因反爬限制无法爬取

### v3 训练管线执行结果
- **数据集**: 27 真实用户 → 600 合成样本 → 627 总计
  - 分层分割: train=17 真实, val=5 真实, test=5 真实
  - 自适应变体数: 8（因 n=27 < 30）
  - 增强比例: 1:22（稀缺类型 ESTJ 权重 ×6，ENTP/ENFJ 权重 ×5）
- **模型**: RandomForest（自动选择，真实样本 17 < 50 阈值）
  - 交叉验证: IE 99.7% | NS 100% | FT 99.2% | JP 99.7%
- **批量测试** (`test_mbti.py` 对 20 人做全量预测):

| 维度 | v2 | v3 | 提升 |
|------|----|----|------|
| IE   | 73.7% | **90.0%** | +16.3% |
| NS   | 63.2% | **75.0%** | +11.8% |
| FT   | 84.2% | **85.0%** | +0.8% |
| JP   | 73.7% | **80.0%** | +6.3% |
| ≥3 维度正确 | 68.4% | **85.0%** | +16.6% |
| 全类型匹配 | — | 65.0% | — |

- **错误分析**:
  - aada (INTJ → ISFP): 低评论率 INTJ 被误判为 S 型 + F 型
  - cabaret (ESTJ → INFP): 书评为主的 ESTJ 行为特征偏向 INFP
  - film101 (ISTJ → INFP): 类似 cabaret，ISTJ 评论风格偏感性
  - gowithvicky (ENTP → INTP): I/E 判断错误（边界区）
  - tjz230 (INFP → ISFP): N/S 判断错误
- **关键发现**: ML 模型远强于纯规则（规则单独: IE 40% NS 45% FT 70% JP 65%），说明模型学到了有效的特征模式
- **特征重要性 Top 3**:
  - IE: comment_rate (0.132), avg_rating (0.129), f_pct_top_rated (0.111)
  - NS: comment_rate (0.216), total_collected (0.170), n_score (0.157)
  - FT: total_collected (0.220), comment_rate (0.141), t_lift (0.137)
  - JP: wish_ratio (0.245), t_lift (0.129), five_star_pct (0.106)

### 后续计划
- **解决反爬**: 等验证码过期或换 IP/账号，继续采集至 200 种子
- **NS 维度**: 仍是最弱环节（N/S 种子比 69:11），需重点采集 S 型用户
- **模型升级**: 真实样本 ≥50 时自动切换 GradientBoosting + GridSearchCV
- **Web 验证**: 端到端测试 MBTI 预测 + LLM 报告生成流程
