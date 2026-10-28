# LabTrace 架构说明

本文描述 LabTrace 的分层结构、数据流，以及 **OceanBase seekdb** 与 **PowerContext** 的职责边界。
所有描述对应 `qoder/backend/app` 与 `qoder/frontend/src` 中的真实代码，未实现的能力会明确标注。

---

## 1. 总体结构

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser · React 18 + TypeScript + Vite + Tailwind                  │
│  Overview / Library / Experiments / AI Research / Memory / Reports  │
│                    / Settings                                       │
│  src/lib/api.ts（30 个端点的唯一出口）· src/state/AppContext.tsx    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP JSON（开发态 vite 代理，生产态 nginx /api）
┌───────────────────────────────▼─────────────────────────────────────┐
│  FastAPI · backend/app                                              │
│                                                                     │
│  api/       health  projects  documents  experiments  memory        │
│             chat    reports                    ← 30 个路由           │
│  schemas.py Pydantic 请求/响应模型（入参校验、上传限制）             │
│  services/  documents  retrieval  experiments  memory  assistant    │
│             reports    embeddings  projects    powercontext         │
│  db/seekdb.py  唯一的 SQL 出口（参数化查询 + 索引管理）              │
│  main.py     lifespan 启停、CORS、SeekDBError→503 /                 │
│              PowerContextError→502 的统一异常处理                    │
└────────────┬──────────────────────────────────┬─────────────────────┘
             │ MySQL 协议（PyMySQL）             │ HTTP（httpx AsyncClient）
             │ embedded: pylibseekdb Unix socket │ Bearer Token（容器模式）
             │ remote:   TCP 2881                │
┌────────────▼──────────────────┐  ┌────────────▼─────────────────────┐
│  OceanBase seekdb 1.4.0       │  │  PowerContext Server 1.2.0       │
│                               │  │                                  │
│  lt_projects      项目 ↔ Scope │  │  Scope     一个项目一个作用域     │
│  lt_documents     文档元数据   │  │  Source    会话/实验原文留痕      │
│  lt_document_chunks            │  │  Memory    六类研究状态 + 版本引用 │
│    VECTOR(384) + HNSW 向量索引 │  │  PreparedContext  打包上下文      │
│    FULLTEXT(ik) 全文索引       │  │  Handoff   finalize→commit→      │
│  lt_experiments   实验记录     │  │            continue（跨会话交接）  │
│    FULLTEXT(ik) 全文索引       │  │                                  │
│  lt_meta          索引配置留痕 │  │  自有 embedded seekdb 存储        │
└───────────────────────────────┘  └──────────────────────────────────┘
```

三个进程可以是一台机器上的三个容器，也可以是原生进程（`scripts/dev-up.sh`）。
前端只与 FastAPI 通信，**浏览器从不直接访问 seekdb 或 PowerContext**，凭据因此只存在于服务端。

---

## 2. 职责边界：谁存什么

这是本项目最重要的一条架构约束，比赛要求"清晰的职责划分"。

### seekdb 负责"可检索的语料与结构化记录"

| 表 | 内容 | 索引 |
| --- | --- | --- |
| `lt_projects` | 项目基本信息 + `pc_scope_id`（指向 PowerContext Scope） | 主键 |
| `lt_documents` | 文档元数据：标题、主题、文件名、类型、页数、字符数、分块数、状态 | `project_id`、`created_at` |
| `lt_document_chunks` | 分块正文、`searchable_text`、`embedding VECTOR(n)`、**页码** | HNSW 向量索引 + ik 全文索引 |
| `lt_experiments` | 实验全字段：目标/假设/方法/模型配置/数据集/结果/指标(JSON)/问题/失败原因/下一步/状态/Markdown 日志 | `project_id`、`created_at`、`dataset` + ik 全文索引 |
| `lt_meta` | 当前全文索引使用的 parser（用于配置变更时判断是否需要重建） | 主键 |

**seekdb 里不存任何模型生成的推测性文字。** 分块正文与实验字段都来自用户上传或用户录入的原文。
周报与助手回答中由模型生成的段落只在 HTTP 响应里返回，不落库。

### PowerContext 负责"可延续的研究状态"

| 能力 | LabTrace 用法 |
| --- | --- |
| **Scope** | 创建项目时同步创建一个 Scope，`scope_id` 写回 `lt_projects.pc_scope_id`。所有记忆操作都以它为隔离边界 |
| **Source** | "保存本次研究进度"时，把会话摘要 + 已完成事项 + 结论 + 待解问题 + 下一步 + 对话转录渲染成一份文本，作为 Source 捕获，`source_id = labtrace-session-<session>-<时间戳>`，metadata 里带上 `project_id` 与相关 `experiment_ids` |
| **Memory** | 六类研究状态：`research_profile`、`project_context`、`decision`、`failure`、`progress`、`next_action`。每条返回精确引用（`memory_ref + entry_id + entry_version_id`）与版本号，支持修订与停用 |
| **PreparedContext** | `/api/memory/context` 与助手回答时调用，把 Scope 内相关内容打包成带字节预算的上下文 |
| **Handoff** | 保存进度时 `finalize`→`commit` 一个交接件（objective / state / disposition / next_action / omissions，每条 statement 都引用上面的 Source）；新会话 `continue` 读取并 resolve |

**PowerContext 里不存论文正文和实验表格**，只存从这些记录中提炼出的研究状态与引用。

### 两者之间的可追踪关联

比赛要求"对记忆更新与实验记录之间的关联设计可追踪的标识"。做法是**双向标注**：

1. `lt_projects.pc_scope_id` — 从 seekdb 侧指向 PowerContext Scope
2. `POST /api/experiments/{id}/to-memory` 写入记忆时：
   - `reason` 字段带 `来自实验记录 <name>（<experiment_id>）`，并把 evidence JSON
     （`origin / experiment_id / project_id / experiment_name / status`）附在后面
   - **但 PowerContext 的 `reason` 是 write-only 的**：`list` 与 `search` 都不会返回它，
     而且长度上限 512 字符。所以记忆正文还会追加一个可见的 ` [exp:<experiment_id>]` 标签，
     用户在 Memory 界面能直接看到这条记忆来自哪条 seekdb 记录，点回实验详情即可核对
3. 保存进度时 Source 的 `metadata` 里带 `experiment_ids`，PowerContext 侧也能反查到证据来源

---

## 3. 后端模块

### `db/seekdb.py` — 唯一的 SQL 出口

- **两种模式**，由 `SEEKDB_MODE` 选择：
  - `embedded`：`pylibseekdb.aopen(path)` 在进程内起一个 OceanBase 运行时，
    通过它返回的 **Unix socket** 连接（仅 Linux / macOS）
  - `remote`：用 `host/port/user/password/database` 走 TCP 连接独立 seekdb 服务端
- 每次查询新建一个 PyMySQL 连接（`DictCursor`、`autocommit`），在 `asyncio.to_thread` 中执行，
  不持有长连接池——科研工作台的并发很低，这样避免了连接失效与 embedded 生命周期纠缠的问题
- `execute_batch` 在一个事务里跑多条语句（批量导入分块、批量导入实验）
- **索引管理**：
  - `CREATE VECTOR INDEX ... WITH (distance=l2, type=hnsw)`
  - `CREATE FULLTEXT INDEX ... WITH PARSER <ik|ngram|space|beng>`
  - seekdb 对向量索引和全文索引**没有 `IF NOT EXISTS`**，所以先用
    `information_schema.statistics` 判断存在性；在已有向量索引的列上重复创建会返回
    错误 1235 而不是重名错误，必须前置检查
  - parser 是建索引时固定的、`information_schema` 查不出来，因此把当前 parser 记在
    `lt_meta`，配置变化时先 `DROP INDEX` 再重建

### `services/documents.py` — 上传、抽取、分块、入库

- 类型白名单 + MIME 校验 + 大小上限（`LABTRACE_MAX_UPLOAD_MB`，默认 20 MB）
- PDF：PyMuPDF 逐页 `get_text()`，**页号随分块一起保存**
- Markdown / TXT：整体作为一页原样保存（不改写用户文本）
- 分块：按段落聚合到 `DOCUMENT_CHUNK_MAX_CHARS`（默认 700），过短的尾块合并进上一块而不是丢弃
- 每块生成 `searchable_text`（标题 + 主题 + 正文）与向量，批量写入
- `list_documents` 返回 `char_count`，供前端核对入库是否完整

### `services/retrieval.py` — 三种检索模式

三条路径都是真实 SQL，没有缓存、没有预计算：

```sql
-- keyword
SELECT ..., MATCH(c.searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS fts_score
FROM lt_document_chunks c JOIN lt_documents d ON d.doc_id = c.doc_id
WHERE c.project_id = %s AND MATCH(...) AGAINST (%s IN NATURAL LANGUAGE MODE)
ORDER BY fts_score DESC, c.chunk_index LIMIT k

-- vector
SELECT ..., l2_distance(c.embedding, '<向量字面量>') AS l2_distance
FROM lt_document_chunks c JOIN lt_documents d ON d.doc_id = c.doc_id
WHERE c.project_id = %s
ORDER BY l2_distance APPROXIMATE LIMIT k

-- hybrid：两路都跑，再 RRF 融合
score = Σ 1 / (60 + rank_leg)
```

- 向量字面量在拼进 SQL 前由 `format_vector` 校验为纯数字列表（防注入）；其余参数一律 `%s` 占位
- 每条命中带 `matched_by`：`fulltext` / `vector` / `fulltext,vector`，
  以及 `fts_score`、`l2_distance`、`score`，前端可解释性面板直接展示
- 返回结构里带 `engine` 与 `sql_mode` 字段，明确写出本次用了哪些 seekdb 特性

### `services/experiments.py` — 实验记录

CRUD、批量导入、状态筛选、全文检索（复用 `lt_experiments_ft_idx`）、
两两对比（字段差异 + 指标 Δ）、按指标取最优。指标以 JSON 文本存 `metrics` 列，
读取时解析，对比时按数值算 Δ。

### `services/memory.py` — PowerContext 记忆引擎

- `MEMORY_KINDS` 六类 + `KIND_LABELS` 中文标签
- `write_memory` 校验 kind，调用 `/v1/memory/remember`，返回引用与版本
- `list_memories` / `search_memories` 分别走 `/v1/memory/entries/list` 与 `/v1/memory/search`
  并按 kind 分组
- `revise_memory` / `retire_memory` 需要回传精确引用；遇到 `revision_conflict`（HTTP 409，
  说明引用已过期）时 `_retry_on_stale_revision` 会重新拉取当前版本再试一次
- `save_progress`：Source → 多条 Memory → Handoff(finalize→commit)，
  单条记忆写失败不会中断整体保存（`_safe_write` 记录 warning 并跳过）
- `restore_progress`：`continue_handoff(selection="latest")` + `list_memories` +
  `prepare_research_context`，任一失败都降级为带错误信息的部分结果，而不是整个接口报错
- `_render_restore_answer` 把上面三部分渲染成一段中文"上次研究到哪里了"的回答

### `services/assistant.py` — 意图路由与可解释回答

```python
Intent = Literal["paper", "experiment", "memory", "mixed"]
```

- `classify_intent(message)` 用 `_PAPER_HINTS` / `_EXPERIMENT_HINTS` / `_MEMORY_HINTS`
  三组关键词打分：命中 ≥2 组或一组都没命中时判为 `mixed`（宁可多取数据源，也不漏证据）
- 按意图取证据：paper → seekdb 混合检索；experiment → seekdb 实验检索；
  memory → PowerContext PreparedContext + Memory search + Memory list；mixed → 全部
- `_SYSTEM_PROMPT` 五条规则，其中关键的两条：
  证据不足时必须回答"现有证据无法确认"，以及必须区分"数据库记录"与"模型推测"
- 响应里带 `data_sources`（每项含 `kind`、命中数、是否用了 SQL / HTTP）与 `llm_used`
- 未配置 LLM 时走 `_evidence_only_answer`：把真实检索到的证据组织成结构化回答，
  并明确标注未使用模型

### `services/reports.py` — 周报

按 `project_id + [start_date, end_date]` 从 seekdb 聚合真实记录（文档、实验、指标），
从 PowerContext 聚合 decision / failure / next_action，渲染成 Markdown。
配置了 LLM 时会再让模型润色概述段落，`llm_used` 如实标注；未配置时走确定性模板，
所有数字都直接来自数据库。

### `services/embeddings.py` — 向量

- 配置了 `OPENAI_BASE_URL + OPENAI_API_KEY + EMBEDDING_MODEL` 时调用 OpenAI 兼容的
  embeddings 接口
- 否则用 `local-hash-fallback`：对分块文本做确定性哈希，铺满 `EMBEDDING_DIMENSION` 维并归一化。
  **这是一个确定性回退，不是语义模型**——它保证向量列、HNSW 索引与 ANN 查询链路真实可跑、
  结果可复现，但语义相近的文本不会自然靠近。这一取舍在 `/api/health` 与 Settings 页面
  都会如实显示 `embedding.provider`，不假装成语义检索

---

## 4. 数据流示例

### 4.1 上传一篇论文

```
POST /api/documents/upload (multipart: project_id, title, topic, file)
  → schemas 校验类型/大小
  → documents.extract_pages：PDF 逐页 PyMuPDF；md/txt 原样一页
  → documents.chunk_pages：段落聚合，保留 page_no
  → embeddings.embed_batch：OpenAI 或 local-hash-fallback
  → db.execute_batch：INSERT lt_documents + N × INSERT lt_document_chunks（一个事务）
  ← { doc_id, chunk_count, page_count, embedding_provider, file_type, ... }
```

### 4.2 混合检索并引用回溯

```
POST /api/search { project_id, query, mode: "hybrid", limit: 6 }
  → retrieval._keyword_leg  → seekdb FULLTEXT
  → retrieval._vector_leg   → seekdb ANN
  → retrieval._fuse         → RRF(k=60)，合并 matched_by
  ← { engine, sql_mode, total, citations: [{doc_id, chunk_id, page_no,
                                            location, content, score, matched_by}] }

GET /api/documents/{doc_id}/chunks?project_id=...   ← 点击引用后回溯原文分块
```

### 4.3 保存研究进度 → 新会话恢复

```
POST /api/memory/save-progress
  → projects.require_scope（读 lt_projects.pc_scope_id）
  → memory.save_progress
      → PowerContext POST /v1/sources/content        （会话原文留痕）
      → PowerContext POST /v1/memory/remember × N     （progress/decision/failure/next_action）
      → PowerContext POST /v1/handoff/finalize        （draft → prepared）
      → PowerContext POST /v1/handoff/commit          （→ committed，返回 reference）
  ← { source, memories[], handoff: {status: "committed", reference} }

—— 关掉浏览器、开一个全新会话 ——

POST /api/memory/restore?project_id=...
  → PowerContext POST /v1/handoff/continue (selection=latest)  → resolved
  → PowerContext POST /v1/memory/entries/list                  → 按 kind 分组
  → PowerContext POST /v1/context/prepare                      → PreparedContext
  → _render_restore_answer                                     → 中文回答
  ← { handoff, memories[], grouped, prepared_context, answer }
```

跨会话能力完全由 PowerContext 的服务端状态提供，**前端没有用 localStorage 存任何研究内容**
（`AppContext` 只缓存"当前选中的项目 ID"这一个 UI 偏好）。

### 4.4 助手提问

```
POST /api/chat { project_id, message, session_id }
  → assistant.classify_intent → paper | experiment | memory | mixed
  → 按意图取证据（seekdb SQL / PowerContext HTTP，可能都取）
  → 组装 data_sources（可解释性面板数据）
  → llm_enabled ? _chat(messages) : _evidence_only_answer(evidence, question)
  ← { intent, answer, citations[], data_sources[], llm_used }
```

---

## 5. 项目隔离

比赛要求"所有科研数据按项目隔离"。实现是**在存储层就隔离，而不是在应用层过滤后再兜底**：

- seekdb：每张表都有 `project_id` 列并建了索引，所有查询的 `WHERE` 都带它；
  文档、分块、实验的读取接口都要求传 `project_id`，跨项目 ID 直接查不到
- PowerContext：一个项目一个 Scope，`scope_id` 是每次记忆调用的必填参数；
  不同项目的记忆在 PowerContext 侧物理隔离
- 删除项目时清理 seekdb 侧的行；PowerContext Scope 内的记忆**保留**，
  以便审计（这一点在 `e2e_demo.py` 的输出里也写明了）

---

## 6. 错误处理与可观测性

- `SeekDBError` → HTTP 503，`PowerContextError` → HTTP 502，都带原始信息片段（截断 800 字符）
- `GET /api/health` 返回 seekdb（connected / mode / version）、PowerContext
  （url / reachable / ready / capabilities）、llm（configured）、embedding
  （provider / dimension）四组状态，前端 Settings 页与 Overview 顶栏直接展示
- `GET /api/meta` 返回维度、parser、上传上限等配置，前端据此显示约束
- 后端启动日志一行汇总四个子系统状态；关键写操作（记忆同步、Handoff 失败）都有
  `logger.info` / `logger.warning`
- 降级策略：PowerContext 不可用时，论文库与实验追踪仍然完全可用；
  LLM 未配置时，检索与记录功能完全可用。任何一层失败都不会让整个工作台白屏

---

## 7. 前端结构

```
src/
├── main.tsx / App.tsx        React Router 路由 + TanStack Query Provider
├── index.css                 Tailwind + 自定义工具类
│                             lt-card / lt-panel / lt-muted / lt-label /
│                             lt-input / lt-gradient-text
├── lib/api.ts                30 个端点的类型化封装（唯一的 HTTP 出口）
├── lib/utils.ts              cn() 等
├── state/AppContext.tsx      当前项目、服务健康状态、全局 Toast
├── components/
│   ├── layout/AppLayout.tsx  左侧导航 + 顶栏（项目切换、健康指示灯）
│   ├── Markdown.tsx          轻量 Markdown 渲染（周报、实验日志）
│   └── ui/                   Modal（含确认态）· Toast · primitives
│                             （Button/Card/Input/Select/Badge/EmptyState/Spinner）
└── pages/
    ├── Overview.tsx          仪表盘 + 「继续上次研究」+ 恢复结果面板
    ├── Library.tsx           上传 · 文档列表与筛选 · 三模式检索 · 引用回溯
    ├── Experiments.tsx       列表/筛选 · 创建编辑 · 批量导入 · 对比 · 最优 ·
    │                         全文检索 · 写入记忆
    ├── AIResearch.tsx        提问 · 意图与数据源面板 · 引用点击跳转
    ├── Memory.tsx            六类分组 · 保存进度 · 恢复 · 修订/停用 · 引用查看
    ├── Reports.tsx           日期区间 · 生成 · 预览/编辑/复制/下载
    └── Settings.tsx          服务连接状态 · 配置只读展示 · 项目创建/切换
```

设计取向：桌面优先、信息密度高、深色为主（支持浅色）。
不引入 React Flow 等重型可视化依赖（功能 6 尚未开发），
也没有引入 shadcn/ui 的 CLI 生成物——`components/ui/primitives.tsx` 是一组
与 shadcn 风格一致的手写基础组件，减少依赖与构建体积。

---

## 8. 未实现 / 有意留空的部分

如实列出，避免夸大：

| 项 | 状态 |
| --- | --- |
| 功能 6 科研知识关联图（React Flow） | **未实现**，按比赛要求在核心功能通过验收后再做 |
| PowerContext 的自动记忆抽取（extract）/ Topic Memory / Profile | **未验证**。当前部署未配置模型提供方，`/v1/memory/flush` 返回 422 `capability_not_supported (extract)`，`/v1/topic-memory/flush` 返回 503，`/v1/profile/flush` 返回 `{"status":"disabled"}`。因此 PreparedContext 会是 `status: empty`，LabTrace 的记忆写入全部走显式的 `/v1/memory/remember`。配好 `POWERCONTEXT_SERVER_INFERENCE_*` 后这条链路应能启用，但本项目没有实测过 |
| LLM 生成式回答 | 代码路径完整，但**本次验证全程未配置 API Key**，所有测试与演示都在 `llm_used=false` 下完成 |
| 真实语义向量 | 未配置 `EMBEDDING_MODEL`，用的是 `local-hash-fallback` 确定性向量 |
| 云端托管 OceanBase 实例 | 未验证，只验证了 embedded seekdb 与官方 `oceanbase/seekdb` 容器 |
| Qoder Sites 公开发布 | 展示站已构建（`qoder/site/`，纯静态自包含单页），**发布动作未完成**，需要账号权限（见 docs/DEPLOYMENT.md §6） |
