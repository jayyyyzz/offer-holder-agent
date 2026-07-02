# 基于 RAG 与任务流规划的港校 Offer Holder 入学准备 Agent

面向已经获得香港高校 offer 的内地学生，尤其是授课型硕士（TPG）学生。

项目目标不是只回答“某个问题”，而是把 offer 后分散在学校官网、签证页面、住宿页面、缴费页面、FAQ 和学校邮件里的信息，整理成一个可执行、可追踪、有优先级、带官方依据的个人入学准备任务系统。

当前仓库包含以下部分：

- 第一阶段：官方页面清单、爬取、正文归档、crawl log、基础 CSV schema。
- 初步 Agent：本地检索 + 规则意图识别 + 任务规划 + 风险提醒 + CLI 输出。
- 数据增强：PDF 正文抽取 + FAQ 候选抽取 + FAQ 清洗评分 + 数据质量审计。

## 项目结构

```text
.
├── source_list.csv
├── data/
│   ├── raw_pages/                 # 爬取后的官网正文文本，本地生成，默认不提交
│   ├── cleaned/
│   │   ├── tasks.csv              # 已导出的初始任务模板
│   │   ├── tasks_enriched.csv     # 任务模板 + 官方证据增强副本
│   │   ├── tasks_reviewed.csv     # 人工审核后的正式任务表
│   │   ├── task_evidence.csv      # 从官方 FAQ 抽出的任务字段证据
│   │   ├── faq.csv
│   │   ├── faq_cleaned.csv        # 已清洗、可入库的结构化 FAQ
│   │   ├── schools.csv
│   │   └── user_states.csv        # 本地用户状态表，当前为空表头
│   └── metadata/
│       ├── crawl_log.csv          # 追加式爬虫日志
│       ├── crawl_summary.csv      # 每个 source 的最新状态
│       ├── data_quality_report.csv
│       ├── faq_quality_report.csv
│       ├── tasks_enriched_review.csv
│       ├── task_review_decisions.csv
│       ├── raw_page_index.csv     # raw_pages 正文归档索引
│       ├── phase1_manifest.csv    # 第一阶段产物清单
│       ├── schema_dictionary.csv  # CSV 字段字典
│       └── last_llm_prompt.md     # 示例：基于证据生成的 LLM prompt
├── knowledge_base/
│   ├── audit_data_quality.py
│   ├── build_chunks.py
│   ├── clean_faq.py
│   ├── enrich_tasks.py
│   ├── extract_task_evidence.py
│   ├── extract_faq.py
│   ├── phase1_outputs.py
│   ├── vector_index.py
│   ├── chunks.csv                 # 已生成的本地检索块
│   └── vector_index.csv           # 无依赖 sparse vector index
├── crawler/
│   ├── crawl_pages.py
│   ├── dynamic_crawl_pages.py
│   ├── expand_faq_pages.py
│   └── summarize_crawl.py
├── agent/
│   ├── intent_router.py
│   ├── llm_prompt.py
│   ├── rag_retriever.py
│   ├── task_planner.py
│   ├── user_state.py
│   ├── risk_checker.py
│   └── response_generator.py
├── app/
│   ├── console.py
│   ├── dashboard_api.py        # 结构化 dashboard JSON API
│   └── frontend_server.py      # 本地前端静态资源 + API 服务
├── frontend/
│   ├── index.html              # React 构建后的入口页
│   └── assets/                 # React 构建产物（JS/CSS）
├── frontend-react/
│   ├── src/                    # React 源码
│   ├── package.json
│   └── vite.config.js          # 构建输出到 ../frontend
├── docs/
│   └── phase2_initial_agent_implementation.md
├── tests/
├── requirements.txt
└── README.md
```

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
```

`playwright install chromium` 只在首次使用浏览器渲染采集时需要。

## 第一阶段：爬取官方页面

少量试跑：

```powershell
.\.venv\Scripts\python -m crawler.crawl_pages --max-priority 1 --limit 5
```

按学校或页面类型筛选：

```powershell
.\.venv\Scripts\python -m crawler.crawl_pages --school HKUST --school CUHK
.\.venv\Scripts\python -m crawler.crawl_pages --page-type visa --max-priority 1
```

覆盖已有 raw text：

```powershell
.\.venv\Scripts\python -m crawler.crawl_pages --school HKU --force
```

PDF 支持：

- 当前爬虫已支持 `application/pdf` 和 `.pdf` URL。
- PDF 正文会用 `pypdf` 抽取，并保存成与 HTML 页面一致的 raw text 格式。
- HKU Master Registration Guide 已验证可抽取，约 6,198 字符。

已知限制：

- CityU 页面可能对普通 HTTP 客户端返回 WAF 挑战，因此静态爬虫会标记为 `soft_blocked`；可用 `crawler.dynamic_crawl_pages` 进行浏览器渲染采集。
- PDF 抽取面向文本检索，不保证版面还原；表格、扫描件或复杂排版可能需要 `pdfplumber` 或 OCR。

浏览器渲染采集 CityU：

```powershell
.\.venv\Scripts\python -m crawler.dynamic_crawl_pages --school CityU --force
```

只抓取单个页面类型：

```powershell
.\.venv\Scripts\python -m crawler.dynamic_crawl_pages --school CityU --page-type visa --force
```

生成最新状态汇总和数据质量报告：

```powershell
.\.venv\Scripts\python -m app.console --summarize-crawl
.\.venv\Scripts\python -m app.console --audit-data
```

这两个命令建议在每轮静态/动态爬取、PDF 抽取或 FAQ 抽取之后都跑一次。
单独运行 `--audit-data` 时也会先刷新 `crawl_summary.csv`。

## 初步 Agent：构建本地知识库与任务模板

从 `data/raw_pages/*.txt` 生成检索块；如果 `data/cleaned/faq_cleaned.csv` 已存在，会自动把结构化 FAQ 也加入知识库：

```powershell
.\.venv\Scripts\python -m app.console --build-kb
```

导出 8 校 x 8 类初始任务模板：

```powershell
.\.venv\Scripts\python -m app.console --export-seed-tasks
```

当前本地已生成：

- `knowledge_base/chunks.csv`：847 条 chunks，其中 599 条来自 raw pages，248 条来自 `faq_cleaned.csv`。
- `knowledge_base/vector_index.csv`：847 条 sparse vector index 记录，作为 Chroma / FAISS 前的无依赖过渡层。
- `data/cleaned/tasks.csv`：64 条任务模板。
- `data/cleaned/tasks_enriched.csv`：64 条增强任务模板，其中 35 条匹配到官方任务证据。
- `data/cleaned/task_evidence.csv`：446 条任务证据，用于后续替换/增强任务模板。
- `data/cleaned/user_states.csv`：用户状态持久化表，当前只有表头，未写入真实用户。
- `data/cleaned/faq.csv`：252 条 FAQ 候选。
- `data/cleaned/faq_cleaned.csv`：248 条已清洗 FAQ，可直接作为结构化 FAQ chunk 入库。
- `data/metadata/crawl_summary.csv`：56 条 source 最新状态，当前 40 个 `success`、16 个 `success_dynamic`。
- `data/metadata/data_quality_report.csv`：56 条覆盖度审计，当前 56 个 `ok`、0 个 `weak`、0 个 `blocker`。
- `data/metadata/faq_quality_report.csv`：252 条 FAQ 质量记录，当前 248 条 `keep`、4 条 `reject`。
- `data/metadata/raw_page_index.csv`：57 条 raw page 正文归档索引。
- `data/metadata/phase1_manifest.csv`：17 条第一阶段输入、输出、元数据产物清单。
- `data/metadata/schema_dictionary.csv`：187 条 CSV 字段说明。
- `data/metadata/last_llm_prompt.md`：一次 HKUST 签证问答生成的 grounded prompt 示例。

抽取 FAQ 候选：

```powershell
.\.venv\Scripts\python -m app.console --extract-faq
```

如需扫描所有页面而不只 FAQ 页：

```powershell
.\.venv\Scripts\python -m app.console --extract-faq --all-pages
```

对需要点击展开 accordion / collapse 才能看到答案的 FAQ 页，先运行点击展开采集：

```powershell
.\.venv\Scripts\python -m crawler.expand_faq_pages --from-manual-review --force
```

当前人工复核队列中，CUHK、HKBU、PolyU FAQ 已通过点击展开和链接保留解决；HKUST FAQ 已通过人工复制正文导入解决。

如遇到 WAF 页面但你能手动复制官方正文，可导入 manual capture：

```powershell
.\.venv\Scripts\python -m crawler.import_manual_page `
  --input "path\to\pasted-text.txt" `
  --school HKUST `
  --page-type faq `
  --source-url "https://fytgs.hkust.edu.hk/admissions/faq" `
  --title "FAQ | HKUST Fok Ying Tung Graduate School"
```

清洗 FAQ 候选并生成质量报告：

```powershell
.\.venv\Scripts\python -m app.console --clean-faq
```

清洗规则会处理常见问题编号、过短片段、模板占位符、导航残留和同校重复问题。`faq_quality_report.csv` 保留 `keep` / `review` / `reject` 决策，方便人工复核；`faq_cleaned.csv` 只保存可直接入库的 FAQ。

从 cleaned FAQ 抽取任务证据：

```powershell
.\.venv\Scripts\python -m app.console --extract-task-evidence
```

`task_evidence.csv` 是审阅用的中间表，不会覆盖 `tasks.csv`。它把官方 FAQ 中的 `deadline`、`required_document`、`action_url`、`fee_amount`、`action_instruction` 等证据抽出来，供后续人工确认后再合并到任务模板。

生成证据增强任务表，不覆盖原任务表：

```powershell
.\.venv\Scripts\python -m app.console --enrich-tasks
```

生成人工复核报告，优先标出 `pay_deposit`、`submit_conditions` 这类高歧义任务：

```powershell
.\.venv\Scripts\python -m app.console --review-enriched-tasks
```

这一步会生成 `data/metadata/tasks_enriched_review.csv`，主要目的不是再次自动“做决定”，而是把最值得人工看的任务提前筛出来。当前规则重点关注：

- `pay_deposit`、`submit_conditions` 这类容易混入 general admission FAQ 的任务
- 有 candidate evidence 但没有 keep 级 usable evidence 的任务
- 仍存在 `review/missing` 证据、或同一任务同时出现 `keep` 和 `reject` 证据的情况

建议审阅顺序：

1. 先看 `review_priority=high`
2. 再对照 `official_*_evidence`、原始 `source_url`、offer letter / portal / 学院邮件
3. 确认后再决定是否把这些候选证据用于最终问答链路

把人工复核结果真正落成“可供主流程使用”的任务表：

```powershell
.\.venv\Scripts\python -m app.console --init-task-review-decisions
.\.venv\Scripts\python -m app.console --build-reviewed-tasks
```

这两步会新增两层文件：

- `data/metadata/task_review_decisions.csv`：给人工填写 `reviewer_decision`、`reviewed_*` 字段和备注的决策表。
- `data/cleaned/tasks_reviewed.csv`：真正给主问答和个人任务清单读取的“已审核任务表”。

当前审核决策语义是：

- `approve`：沿用原候选证据，标记为人工确认通过
- `approve_with_edits`：允许用 `reviewed_*` 字段覆盖原候选证据
- `reject`：清空该任务的官方候选证据，避免把错误证据带进主链路

当你希望主流程优先使用人工审核后的任务表时，改用：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --use-reviewed-tasks
```

这里保留了一个很重要的边界：`tasks_enriched.csv` 仍然是“候选证据层”，`tasks_reviewed.csv` 才是“人工确认后可直接给主链路用的任务层”。

生成向量索引：

```powershell
.\.venv\Scripts\python -m app.console --build-vector-index
```

默认会生成无依赖 `sparse` 索引。如果要试用可选的 `Chroma` 后端，可显式开启：

```powershell
.\.venv\Scripts\python -m app.console `
  --build-vector-index `
  --vector-backend chroma `
  --embedding-provider hash
```

当前实现保留了两层设计：

- `sparse`：默认后端，完全本地、可审计、无外部服务依赖
- `chroma`：可选后端，用于更接近语义检索的实验路径；默认可用 `hash` embedding，本地可跑；若设置 `--embedding-provider openai`，则会调用 OpenAI Embeddings API

主问答流程默认仍走关键词检索；如需显式试用语义检索：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --retrieval-mode semantic `
  --vector-backend chroma `
  --use-enriched-tasks
```

如果语义检索路径失败或没有返回结果，当前实现会自动回退到原有关键词检索链路。

生成第一阶段归档元数据：

```powershell
.\.venv\Scripts\python -m app.console --prepare-phase1-outputs
```

该命令会生成：

- `data/metadata/raw_page_index.csv`：索引每个 `raw_pages/*.txt` 的学校、页面类型、来源 URL、标题、抽取方式、正文长度。
- `data/metadata/phase1_manifest.csv`：汇总 source、raw、crawl log、cleaned、quality report、chunks 等产物是否存在、行数/文件数和更新时间。
- `data/metadata/schema_dictionary.csv`：保存第一阶段核心 CSV 的字段字典，便于后续 RAG、任务规划和人工复核对齐字段含义。

导出未来接 LLM 时使用的 grounded prompt：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --export-llm-prompt
```

如需直接调用真实 OpenAI Responses API 生成最终回答：

```powershell
$env:OPENAI_API_KEY="你的 API Key"

.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --use-enriched-tasks `
  --use-openai-response `
  --openai-model gpt-5.5 `
  --openai-run-metadata-dir data/metadata/openai_runs
```

当前 LLM 接入遵守这几个边界：

- 仍先由本地链路生成 grounded prompt，再调用 Responses API
- 不把 API key 写入代码或 README，统一从环境变量读取
- `user_deadline_at` / `user_reminder_at` 与 `official_deadline_evidence` 仍严格区分
- 即使启用 LLM，底层任务规划、风险检查、证据检索仍沿用本地可审计逻辑

这一轮又往前推进了一步：Responses API 现在会把每次调用的关键 metadata 落到 `data/metadata/openai_runs/`，包括：

- 模型名、prompt 字符数、`reasoning_effort`、`text_verbosity`
- 实际尝试次数、retry 次数、HTTP 状态
- 是否 fallback 到本地格式化回答，以及 fallback 原因
- 成功时的 `response_id` 与简短输出摘要

这一步为什么重要：

- 之前如果真实 API 调用失败，只能从终端报错大致判断。
- 现在能把“失败在哪一轮、是否重试过、为什么降级、本次用了哪个模型”留成可复盘的本地记录。
- 这对后续调 prompt、调超参、排查网络抖动或配额问题都更实用。

保存 / 读取本地用户状态：

```powershell
.\.venv\Scripts\python -m app.console `
  --user-id demo_hkust `
  --school HKUST `
  --accepted-offer `
  --paid-deposit `
  --message "我下一步要做什么？" `
  --save-user-state

.\.venv\Scripts\python -m app.console `
  --user-id demo_hkust `
  --load-user-state `
  --message "我现在还没申请签证，优先做什么？"
```

## 个人任务工作流

除了“问下一步做什么”，当前 CLI 还支持把任务规划结果落成一个可持续维护的个人任务清单。这里的设计目标是把三类信息分开但串起来：

- `user_states.csv`：用户整体状态，例如是否已接受 offer、是否已交留位费。
- `user_task_states.csv`：某一条任务的个人状态，例如 `apply_student_visa` 是否已开始、你的个人 deadline 是哪一天、什么时候提醒。
- `tasks_enriched.csv`：学校官方候选证据增强过的任务模板，用来给个人任务提供官方入口和候选 deadline/document/action 依据。
- `tasks_reviewed.csv`：经过人工审核后的任务模板；如果你已经完成复核，个人任务视图和主问答更适合读取这一层。

先写入某条任务的个人状态：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --user-id demo_hkust `
  --school HKUST `
  --task-code apply_student_visa `
  --task-stage visa `
  --set-task-status in_progress `
  --deadline-at 2026-08-01 `
  --deadline-timezone Asia/Hong_Kong `
  --deadline-source portal `
  --reminder-at 2026-07-25T09:00:00 `
  --reminder-status pending
```

查看当前个人任务清单：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --user-id demo_hkust `
  --school HKUST `
  --load-user-state `
  --list-user-tasks `
  --use-reviewed-tasks `
  --include-completed-tasks
```

查看已记录的 deadline / reminder：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --user-id demo_hkust `
  --list-task-reminders `
  --load-user-state `
  --status-filter in_progress
```

查看“今天 / 近期要处理什么”：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --user-id demo_hkust `
  --list-task-agenda `
  --load-user-state `
  --use-reviewed-tasks `
  --agenda-days 7 `
  --agenda-timezone Asia/Hong_Kong
```

如需固定查看某一天的 agenda（便于复盘或写测试）：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --user-id demo_hkust `
  --list-task-agenda `
  --agenda-date 2026-07-25 `
  --agenda-days 3 `
  --agenda-timezone Asia/Hong_Kong
```

### 这一步为什么重要

这一步把系统从“会回答问题的原型”往“能跟踪个人推进状态的工具”推进了一层。实现上有几个明确的边界：

- `set-task-status` 只更新用户侧状态，不修改学校官方任务模板。
- `deadline_at` / `reminder_at` 是个人侧记录，和 `official_deadline_evidence` 这种官方候选证据分开保存，避免混淆。
- `agenda` 视图优先按提醒时间排序；没有提醒时，再退回个人截止时间。
- `agenda` 会把任务分成 `已逾期`、`今天`、`未来 N 天`，更适合日常使用，而不是每次都从完整任务表里人工筛选。

### 当前新增命令

```text
--list-user-tasks
--list-task-reminders
--list-task-agenda
--status-filter
--include-completed-tasks
--agenda-date
--agenda-days
--agenda-timezone
--review-enriched-tasks
--init-task-review-decisions
--build-reviewed-tasks
--use-reviewed-tasks
--vector-backend
--retrieval-mode
--chroma-dir
--chroma-collection-name
--embedding-provider
--embedding-dimensions
--use-openai-response
--openai-model
--openai-run-metadata-dir
--review-pending-export
```

## 本地前端工作台

当前前端已经升级为 React，并保留了原来的 Python 部署方式：

- `frontend-react/`：React 源码与 Vite 构建配置
- `frontend/`：React 构建后的静态产物，由 `app/frontend_server.py` 直接提供

当前前端遵循两个边界：

- 不直接解析 CLI 文本，而是读取 `app/dashboard_api.py` 提供的结构化 JSON。
- React 构建产物继续由 `app/frontend_server.py` 统一提供静态资源和 `/api/dashboard`。

启动方式：

```powershell
.\.venv\Scripts\python.exe -m app.frontend_server --port 8123
```

React 源码改动后重新构建：

```powershell
cd frontend-react
npm.cmd install
npm.cmd run build
```

启动后访问：

- `http://127.0.0.1:8123/`：前端工作台
- `http://127.0.0.1:8123/api/dashboard`：结构化 dashboard JSON
- `http://127.0.0.1:8123/health`：健康检查

前端当前展示的内容包括：

- 学校、`user_id`、agenda 天数、时区筛选
- 任务源切换：`reviewed` / `enriched` / `builtin`
- 汇总指标：进行中任务、已记录状态、提醒、今天、逾期
- agenda 分桶：`已逾期`、`今天`、`未来 N 天`
- reminder 列表
- 任务清单 + 任务详情面板
- 个人 deadline/source_ref、人工审核状态、官方证据摘要、官方链接
- 个人任务状态写回表单：可直接写入 `user_task_states.csv`
- 编辑流增强：支持“恢复为已保存值”“清空当前编辑”“未保存改动提示”
- 已保存状态摘要：能直接看到当前本地持久化值，而不是只看输入框草稿
- 写回追踪字段：展示最近写回时间和状态更新时间

当前回退策略：

- 优先读取 `data/cleaned/tasks_reviewed.csv`
- 若不存在，自动回退到 `data/cleaned/tasks_enriched.csv`
- 若仍不存在，回退到内置任务模板

为什么这一步重要：

- 之前系统已经能“算出下一步任务”，但还主要停留在 CLI。
- 现在它开始有一个更适合日常推进的工作台入口，方便直接查看“今天该做什么”和“为什么这样判断”。
- 页面顶部现在会同时展示“实际使用的任务源”和“你请求的任务源”，避免 `reviewed` 文件缺失时看起来像状态错乱。
- 前端不再只是只读展示，而是能直接回写个人任务状态。
- 这一步又把写回能力从“能提交”推进到“更像一个完整编辑流”：用户现在能判断自己改了什么、是否已经保存、要不要恢复，减少误写和重复提交。

### 新增的 reviewed-task 批量待审导出

如果你不只想看待审数量，而是想直接拿一份“可以人工处理”的待审清单，现在可以运行：

```powershell
.\.venv\Scripts\python.exe -m app.console `
  --review-pending-export `
  --review-school HKUST
```

默认会输出并写入：

- `data/metadata/task_review_pending_export.csv`

这个导出和 `task_review_pending_summary.csv` 的区别是：

- `summary`：回答“还有多少待审任务”
- `pending_export`：回答“具体是哪几条、为什么待审、优先级是什么、当前候选证据长什么样”

导出表会按 `school -> review_priority -> stage -> task_id` 排序，更适合人工逐条处理。

### 当前验证结果

- `tests/test_console_task_workflow.py`：覆盖个人任务清单、提醒清单、agenda 分桶。
- `tests/test_task_state.py`：覆盖任务状态 round-trip、状态校验、任务排序联动。
- `tests/test_review_enriched_tasks.py`：覆盖高歧义任务的人工复核筛选。
- `tests/test_reviewed_tasks.py`：覆盖人工审核决策初始化、approve / reject / pending 分支、`tasks_reviewed.csv` 接入 `TaskPlanner`，以及新的待审导出。
- `tests/test_openai_responses.py`：覆盖 Responses API payload、输出文本解析、retry，以及新的 run metadata 记录。
- `tests/test_dashboard_api.py`：覆盖 dashboard payload、学校目录、任务源回退、traceability 字段，以及前端写回依赖的个人状态字段。
- React 前端已实际联调通过：页面可加载、任务源切换可用、任务状态可写回；当前构建产物已更新到 `frontend/`。
- 当前全量单元测试：81 个通过。

## 线上部署

当前项目已经补上了最小可部署骨架，保持现有架构不变：

- 前端仍然是 `frontend-react/` 构建到 `frontend/`
- 后端仍然是 `app/frontend_server.py`
- 线上通过容器直接启动 Python 服务，不额外引入新后端框架

仓库里当前保留的部署相关文件包括：

- `Dockerfile`
- `.dockerignore`
- `docker-compose.tencent.yml`
- `deploy/tencent/Caddyfile`
- `deploy/tencent/app.env.example`
- `deploy/tencent/caddy.env.example`
- `deploy/tencent/server-setup.sh`
- `deploy/tencent/deploy.sh`
- `deploy/tencent/update.sh`
- `deploy/env.example`

### 当前推荐的上线方式

当前默认推荐：

- `腾讯云轻量应用服务器（LightHouse）` 作为应用服务器
- `Docker Compose` 编排应用和反向代理
- `Caddy` 自动申请和续签 HTTPS 证书
- `腾讯云域名 / DNSPod` 做域名解析

这样可以直接复用现在的容器启动形态，同时保留可写数据目录，不需要为了平台适配重写服务层。

### 服务当前支持的线上配置

`app/frontend_server.py` 现在已经支持以下环境变量：

```text
PORT
OFFER_AGENT_HOST
OFFER_AGENT_PORT
OFFER_AGENT_RUNTIME_DATA_ROOT
OFFER_AGENT_SEED_DATA_ROOT
OFFER_AGENT_BASIC_AUTH_USER
OFFER_AGENT_BASIC_AUTH_PASSWORD
OFFER_AGENT_READ_ONLY
OPENAI_API_KEY
```

其中最重要的几个是：

- `PORT`：大多数云平台会自动注入
- `OFFER_AGENT_RUNTIME_DATA_ROOT`：线上运行时实际读写的数据目录
- `OFFER_AGENT_SEED_DATA_ROOT`：镜像内的初始种子数据目录
- `OFFER_AGENT_BASIC_AUTH_USER` / `OFFER_AGENT_BASIC_AUTH_PASSWORD`：建议上线时至少先开 Basic Auth
- `OFFER_AGENT_READ_ONLY=false`：如果你要保留线上输入数据能力，需要显式允许写入

### 腾讯云轻量服务器 + `zungit.com` 方式（当前推荐）

#### 1. 先确认腾讯云轻量服务器基础项

建议首版直接用：

- Ubuntu 24.04 LTS
- 2 GB RAM 起步
- 单机部署

你现在是 Windows 本地环境，这不影响部署。后续本地连接服务器，直接用 PowerShell 自带的 `ssh` / `scp` 即可。

在腾讯云轻量服务器控制台里，先确认这几件事：

- 服务器有公网 IPv4
- 轻量服务器防火墙已放行 `22`
- 轻量服务器防火墙已放行 `80`
- 轻量服务器防火墙已放行 `443`

这里有一个容易漏掉的点：腾讯云当前中文官方文档里，Linux 系统镜像默认放通的是 `22`、`80` 和 `ICMP`，`443` 需要你手动加规则，否则 Caddy 的 HTTPS 证书申请会失败。

#### 2. 把域名解析到轻量服务器

在腾讯云域名解析 / DNSPod 中添加：

```text
记录类型: A
主机记录: @
记录值: 你的轻量服务器公网 IPv4

记录类型: A
主机记录: www
记录值: 你的轻量服务器公网 IPv4
```

如果你最终只想使用一个主域名，也可以只保留 `@`。

当前这套部署默认主域名直接用：

```text
zungit.com
```

#### 3. 用 Windows PowerShell 连上服务器

如果腾讯云控制台给你的是密码登录，常见连接方式是：

```powershell
ssh ubuntu@你的服务器公网IP
```

如果你用的是密钥文件，常见方式是：

```powershell
ssh -i C:\Users\jay\.ssh\你的密钥文件 ubuntu@你的服务器公网IP
```

不同镜像用户名可能是 `ubuntu`、`root` 或你自己在控制台创建的用户，以服务器实际登录方式为准。

#### 4. 把代码放到服务器

如果你的 GitHub 仓库已经是最新代码，推荐直接在服务器执行：

```bash
git clone https://github.com/jayyyyzz/offer-holder-agent.git
cd offer-holder-agent
```

如果你本地有还没推到 GitHub 的改动，也可以在 Windows PowerShell 里直接上传：

```powershell
scp -r "C:\Users\jay\Documents\offer holder agent" ubuntu@你的服务器公网IP:/home/ubuntu/offer-holder-agent
```

然后再 SSH 进入服务器：

```bash
cd /home/ubuntu/offer-holder-agent
```

#### 5. 在服务器安装 Docker

进入仓库目录后执行：

```bash
sudo bash deploy/tencent/server-setup.sh
```

这个脚本会安装：

- Docker Engine
- Docker Compose Plugin

#### 6. 准备服务器环境文件

在服务器上复制模板：

```bash
cp deploy/tencent/app.env.example deploy/tencent/app.env
cp deploy/tencent/caddy.env.example deploy/tencent/caddy.env
```

然后至少修改这几个值：

```text
# deploy/tencent/app.env
OFFER_AGENT_BASIC_AUTH_USER=jayz
OFFER_AGENT_BASIC_AUTH_PASSWORD=一个强密码
OFFER_AGENT_READ_ONLY=false
OPENAI_API_KEY=你的真实 key

# deploy/tencent/caddy.env
APP_DOMAIN=zungit.com
```

如果你暂时不想在线上调用模型，也可以先把：

```text
OPENAI_API_KEY=
```

保持为空，先把服务本身跑起来。

#### 7. 启动整套服务

```bash
bash deploy/tencent/deploy.sh
```

这一步会启动：

- `offer-holder-agent` 应用容器
- `caddy` 反向代理容器

其中：

- Caddy 会监听 `80/443`
- 应用容器只暴露内部 `8080`
- HTTPS 证书会由 Caddy 自动申请

#### 8. 首次上线后检查

上线后可直接检查：

```text
https://zungit.com/health
https://zungit.com/
```

如果你先想在服务器本机确认容器是通的，也可以先跑：

```bash
docker compose -f docker-compose.tencent.yml ps
curl http://127.0.0.1:8080/health
```

#### 9. 后续更新发布

后续服务器上拉新代码后，直接执行：

```bash
bash deploy/tencent/update.sh
```

当前仓库已经把 `OFFER_AGENT_BASIC_AUTH_USER` 预设为 `jayz`，所以你实际需要提供给服务器的是：

```text
OFFER_AGENT_BASIC_AUTH_PASSWORD=一个强密码
OPENAI_API_KEY=你的真实 key
APP_DOMAIN=zungit.com
```

### 当前这套“可写版”是怎么工作的

当前线上写入仍然使用 CSV，但做了两层处理：

1. 镜像里保留一份初始种子数据：`/app-seed-data`
2. Docker volume 挂载到 `/app/data`

服务启动时会先执行：

- 如果 `/app/data/cleaned`、`/app/data/metadata` 里缺文件，就从 `/app-seed-data` 复制过去
- 之后实际运行中的 CSV 读写都发生在持久盘里

这样做的好处是：

- 首次启动就有初始数据，不是空盘
- 后续用户写入不会因为容器重建丢失
- 不需要为了第一版上线马上改数据库

### 为什么这版可以保留线上输入数据

因为这次已经不是“临时容器写本地盘”，而是“单实例 + Docker volume + 运行时数据根目录”。

但边界仍然很明确：

- 当前仍然更适合单实例
- 当前仍然没有真正的用户权限体系
- CSV 并发写入能力仍然有限

所以这更像是：

**“可以在线输入和保存数据的 Beta 版”**

### 什么时候应该升级到数据库

当你出现下面任一情况时，就不应该继续只靠 CSV：

- 需要多实例扩容
- 需要多人同时编辑
- 需要用户登录与权限隔离
- 需要审计日志、回滚或更细的写入控制

那时优先考虑把这几层迁出去：

- `user_states.csv`
- `user_task_states.csv`
- `task_review_decisions.csv`
- `openai_runs` metadata

### 这一步为什么重要

这一步不是把项目“换个平台跑一下”，而是明确把本地工具推进成“可以被外部访问的服务”：

- 服务入口可以读取平台端口
- 可以开 Basic Auth
- 可以挂持久磁盘保存 CSV
- 可以在首次启动时自动注入种子数据
- Docker 化后不依赖你本机环境

它的意义是先把上线门槛降下来，同时把“线上可输入数据”控制在一个目前还算稳的边界里。

## 当前部署进度（2026-07-02）

这一轮和线上部署直接相关的工作，已经推进到这里：

1. **腾讯云版本部署骨架已经切好**
   - `Dockerfile` 已经支持先构建 React，再启动 Python 服务
   - `docker-compose.tencent.yml` 已经定义好应用容器 + Caddy 反向代理
   - `deploy/tencent/Caddyfile` 已经接好域名入口和 HTTPS 代理
   - `app/start_server.py` 会在服务启动前先执行 runtime data seed
   - `app/runtime_data.py` 会把镜像里的种子数据复制到运行时数据卷
   - `app/frontend_server.py` 已经支持 Basic Auth、`/health`、以及 read-only / writable 切换

2. **线上“可输入数据”模式已经具备最小闭环**
   - Docker volume 挂载到 `/app/data`
   - 镜像内种子数据目录是 `/app-seed-data`
   - 首次部署不是空数据启动
   - 之后用户在前端写入的状态会落到持久盘而不是临时容器文件系统
   - `tasks_reviewed.csv`、`tasks_enriched_review.csv`、`task_review_decisions.csv` 已补齐首版种子文件，前端默认 `reviewed` 任务源可直接使用
   - 当前 `tasks_reviewed.csv` 共 64 条，其中 31 条保留为 `review_pending`，33 条为 `not_required`

3. **仓库发布前清理已经开始收口**
   - `data/metadata/openai_runs/` 已加入 `.gitignore`
   - 前端联调留下的 demo `user_task_states.csv` 记录已经清空，只保留表头
   - 已重新检查仓库，没有把真实 `OPENAI_API_KEY` 写进代码或文档
   - 部署目录里的运行时环境文件忽略路径已经从 `deploy/do/*` 切换到 `deploy/tencent/*`

4. **腾讯云环境说明已经和真实部署目标对齐**
   - README 已经从 DigitalOcean 迁回腾讯云轻量服务器语义
   - 默认域名示例已经切成 `zungit.com`
   - 部署脚本路径已经统一为 `deploy/tencent/*`
   - 文档已经补上 Windows PowerShell 连接服务器的做法
   - 文档已经明确提示腾讯云轻量服务器需要手动确认 `443` 放通

5. **当前剩下的是服务器实操信息**
   - 这台机器上不需要腾讯云 CLI 也能部署，因为当前方案走 SSH + Docker Compose
   - 真正还缺的是你的轻量服务器公网 IP、SSH 登录用户名，以及密码或私钥文件
   - 如果你希望我继续直接推进到真正上线，这三项是下一步必须补齐的

## 当前部署下一步

如果目标是把这版尽快上线到腾讯云轻量服务器，接下来的顺序应该是：

1. **把当前仓库代码推到你要部署的仓库或服务器**
2. **在腾讯云轻量服务器防火墙里确认 `22`、`80`、`443` 已放通**
3. **在腾讯云域名解析里把 `zungit.com` 的 A 记录指向轻量服务器公网 IP**
4. **在服务器准备 `deploy/tencent/app.env` 和 `deploy/tencent/caddy.env`**
5. **运行 `deploy/tencent/server-setup.sh` 安装 Docker**
6. **运行 `deploy/tencent/deploy.sh` 启动服务**
7. **首轮上线后做一次线上验收**
   - 打开 `https://zungit.com/health`
   - 用 Basic Auth 登录首页
   - 测试一次任务状态写回
   - 确认容器重启后写入数据仍在

## 运行初步 Agent

单次问答：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --top-k 3 `
  --task-limit 4
```

如需让主问答流程优先使用 `tasks_enriched.csv` 中的官方候选证据，可显式开启：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --use-enriched-tasks
```

默认不启用该开关，仍使用代码内置任务模板。开启后，回答会展示 `tasks_enriched.csv` 中的 `official_deadline_evidence`、`official_document_evidence`、`official_action_evidence` 等字段；这些字段仍是“官方候选证据”，需要以原文、学校 portal、offer letter 和学院邮件复核。

如果你已经完成人工复核，希望主问答直接读取“已审核任务表”，则优先使用：

```powershell
.\.venv\Scripts\python -m app.console `
  --school HKUST `
  --message "我已经接受offer，也交了留位费，还没申请签证，下一步做什么？" `
  --use-reviewed-tasks
```

`--use-reviewed-tasks` 会优先读取 `tasks_reviewed.csv`；如果你还在候选证据阶段，再继续使用 `--use-enriched-tasks`。

交互模式：

```powershell
.\.venv\Scripts\python -m app.console --interactive --school HKUST
```

可用状态参数：

```powershell
--accepted-offer
--paid-deposit
--has-conditional
--no-conditional
--conditions-cleared
--visa-submitted
--visa-approved
--housing-applied
--tuition-paid
--registered
```

## 初步 Agent 的技术实现

核心链路：

1. `agent/intent_router.py`：识别学校、阶段、意图和已完成事项。
2. `agent/rag_retriever.py`：从 `knowledge_base/chunks.csv` 或 `data/raw_pages` 检索官方依据；检索结果必须在标题/正文中命中查询扩展词，学校/阶段/页面类型只用于排序，不能单独构成 evidence。
3. `agent/task_planner.py`：根据学生状态生成下一步任务；默认使用内置任务模板，也可通过 `--use-enriched-tasks` 显式读取 `tasks_enriched.csv`。
   现在也支持通过 `--use-reviewed-tasks` 显式读取 `tasks_reviewed.csv`。
4. `agent/risk_checker.py`：发现可能阻塞入学的风险。
5. `agent/response_generator.py`：输出中文任务建议、风险提醒和来源 URL。
6. `app/console.py`：命令行入口。
7. `app/dashboard_api.py`：把任务规划、提醒、agenda、学校目录和用户状态整理成结构化 dashboard payload。
8. `app/frontend_server.py`：提供本地前端静态资源与 `/api/dashboard`、`/health` 接口。
9. `agent/openai_responses.py`：封装 Responses API，请求失败时支持 retry / timeout / incomplete 检测。
10. `knowledge_base/reviewed_tasks.py`：支持按学校重建 reviewed 结果、只导出 pending、输出待审摘要。
11. `knowledge_base/extract_faq.py`：从官方页面正文抽取 FAQ 候选。
12. `knowledge_base/clean_faq.py`：清洗 FAQ 候选、评分并输出人工复核报告。
13. `agent/llm_prompt.py`：生成 grounded prompt，额外约束回答必须稳定带 source_url。
14. `crawler/dynamic_crawl_pages.py`：用 Playwright 浏览器渲染采集 WAF / JS 页面。
15. `crawler/summarize_crawl.py`：从追加式 crawl log 生成每个 source 的最新状态表。
16. `knowledge_base/audit_data_quality.py`：审计 source、raw text、chunks、FAQ、tasks 的覆盖度。

更完整的实现记录见：

```text
docs/phase2_initial_agent_implementation.md
```

## CSV 设计

### source_list.csv

```text
school,page_type,stage,url,priority,need_dynamic,remark
```

### crawl_log.csv

```text
school,page_type,stage,source_url,final_url,priority,need_dynamic,status,
http_status,title,crawled_at,raw_file,content_type,char_count,elapsed_ms,error
```

### crawl_summary.csv

```text
school,page_type,stage,source_url,priority,need_dynamic,latest_status,
latest_http_status,latest_title,latest_final_url,latest_crawled_at,
latest_raw_file,latest_content_type,latest_char_count,attempt_count,
success_count,last_success_at,raw_file_exists,needs_attention,
attention_reason,latest_error
```

### data_quality_report.csv

```text
school,page_type,stage,source_url,latest_status,usable_status,
latest_char_count,usable_char_count,raw_file_exists,chunk_count,
faq_count,task_count,coverage_level,needs_attention,notes
```

### tasks.csv

```text
task_id,school,stage,task_name,description,trigger_condition,deadline,
required_documents,action_url,risk_level,source_url,updated_at
```

### tasks_enriched.csv

```text
task_id,school,stage,task_name,description,trigger_condition,deadline,
required_documents,action_url,risk_level,source_url,updated_at,task_code,
evidence_count,evidence_types,official_deadline_evidence,
official_document_evidence,official_action_evidence,official_action_urls,
official_fee_evidence,evidence_ids,enrichment_status,enriched_at
```

### tasks_enriched_review.csv

```text
task_id,school,task_code,stage,task_name,candidate_evidence_count,
usable_evidence_count,review_evidence_count,rejected_evidence_count,
evidence_quality_status,enrichment_status,official_deadline_evidence,
official_document_evidence,official_action_evidence,official_action_urls,
official_fee_evidence,review_priority,review_reason,suggested_action,generated_at
```

### task_review_decisions.csv

```text
task_id,school,task_code,stage,task_name,review_priority,review_reason,
reviewer_decision,reviewed_deadline_evidence,reviewed_document_evidence,
reviewed_action_evidence,reviewed_action_urls,reviewed_fee_evidence,
reviewer_notes,reviewed_at
```

### tasks_reviewed.csv

```text
task_id,school,stage,task_name,description,trigger_condition,deadline,
required_documents,action_url,risk_level,source_url,updated_at,task_code,
evidence_count,candidate_evidence_count,usable_evidence_count,
review_evidence_count,rejected_evidence_count,evidence_types,
official_deadline_evidence,official_document_evidence,
official_action_evidence,official_action_urls,official_fee_evidence,
evidence_ids,evidence_quality_status,evidence_quality_notes,
enrichment_status,enriched_at,review_priority,review_reason,
review_decision,review_notes,human_review_status,reviewed_at
```

### task_evidence.csv

```text
evidence_id,task_code,school,stage,evidence_type,evidence_text,normalized_value,
source_question,source_url,confidence,updated_at
```

### faq.csv

```text
question,answer,school,stage,category,risk_level,source_url,updated_at
```

### faq_cleaned.csv

```text
question,answer,school,stage,category,risk_level,source_url,updated_at
```

### faq_quality_report.csv

```text
question,answer,school,stage,category,risk_level,source_url,updated_at,
cleaned_question,cleaned_answer,quality_score,decision,quality_notes
```

### schools.csv

```text
school_id,school_name,official_website,offer_holder_url,admitted_student_url,
visa_url,accommodation_url,tuition_url,orientation_url
```

### raw_page_index.csv

```text
raw_file,school,page_type,stage,source_url,final_url,title,content_type,
extraction_method,crawled_at,body_char_count,total_char_count,line_count
```

### phase1_manifest.csv

```text
artifact,path,category,exists,row_count,file_count,updated_at,notes
```

### schema_dictionary.csv

```text
dataset,column,required,description
```

### vector_index.csv

```text
chunk_id,school,page_type,stage,title,source_url,raw_file,token_count,
vector_json,updated_at
```

### user_states.csv

```text
user_id,school,origin,program_type,has_conditional_offer,completed_flags,
notes,updated_at
```

## 测试

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m compileall -q crawler agent app knowledge_base tests
```

当前验证结果：

- 单元测试：81 个通过。
- 编译检查：通过。
- React 构建：通过。

## 产品长期建议

1. 给语义检索补评测和切换策略。当前已经支持 `sparse` + `chroma` 双后端，也支持 `keyword` / `semantic` 两种检索模式；下一步值得准备固定 query，对比召回结果、学校过滤效果和 fallback 命中情况。
2. 把前端编辑流继续推进到“更强约束”的表单体验，例如区分“日期截止”和“精确时间提醒”的输入组件、增加字段级校验、对异常时间格式做更早提示。
3. 把 reviewed-task 批量处理再往前推一步，例如为 `task_review_decisions.csv` 生成更适合人工填写的导出视图，或者补“批量 approve/批量 reject”的半自动工具。
4. 基于已经落地的 `openai_runs` metadata，补一个小型分析脚本或 summary 命令，聚合最近 N 次调用的失败原因、重试分布和 fallback 比例。
5. 如果后续新增 FAQ 页面出现短答案，仍然优先运行 `crawler.expand_faq_pages`，再重新 `--extract-faq`、`--clean-faq`、`--build-kb`。这条建议保留，因为它依然是数据质量层面的长期维护动作。
