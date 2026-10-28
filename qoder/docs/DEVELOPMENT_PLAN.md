> 本文件用于设计与规划。当前验证结论见 `VERIFICATION.md`，本轮工具为 Codex，Qoder 主要开发记录仍待真实证据核实。

# LabTrace 开发计划

> Qoder × OceanBase 2026 开发比赛 · Qoder 赛题（`qoder/` 目录）
> 项目：LabTrace —— AI 科研记忆与知识管理工作台

> **文档性质说明（阶段五回填）**
> 本文是**阶段一产出的开发计划**，保留原始内容作为历史记录，未按最终实现改写。
> 计划中有若干技术判断在后续实测中被推翻，详见 §0。
> **以 [ARCHITECTURE.md](ARCHITECTURE.md)、[TECH_INTEGRATION.md](TECH_INTEGRATION.md)、
> [SETUP.md](SETUP.md) 为准**，那三份文档描述的是已验证的实际实现。

## 0. 计划与最终实现的差异（阶段五回填）

| 计划中的判断 | 实测结果 | 最终实现 |
| --- | --- | --- |
| §2 全文索引用 `WITH PARSER SPACE` | **`space` 与 `beng` 对中文查询命中 0 / 6**，完全不可用 | 默认 `ik`（中文 6/6 命中，英文保持整词），可通过 `SEEKDB_FULLTEXT_PARSER` 改为 `ngram` |
| §2 / §4 混合检索用**单条 SQL**（`WHERE MATCH(...) ... ORDER BY l2_distance(...) APPROXIMATE`） | 单 SQL 无法同时得到全文相关度与向量距离两套排名 | **两路并行**（FULLTEXT 一路、ANN 一路）+ Reciprocal Rank Fusion（k=60），每条命中标注 `matched_by` |
| §4 表结构只有 3 张表，并提到 `lt_experiments_fts_view` | 需要项目↔Scope 映射，也需要记录当前 parser（`information_schema` 查不出来） | 实际 **5 张表**：`lt_projects`、`lt_documents`、`lt_document_chunks`、`lt_experiments`、`lt_meta`；**没有** `lt_experiments_fts_view` |
| §4 `CREATE ... INDEX` 可按常规 DDL 幂等处理 | 向量/全文索引**没有 `IF NOT EXISTS`**；重复建向量索引返回 **1235**（不是重名错误 1061） | 建索引前查 `information_schema.statistics`；parser 变更时先 DROP 再重建 |
| §5 使用 `/v1/work/contracts/create`、`/v1/work/handoffs/prepare-current`、`/v1/work/outcomes/record` | 这条 Work 契约链路不是本项目需要的形态 | 实际用 **`/v1/handoff/finalize` → `/v1/handoff/commit` → `/v1/handoff/continue`**，外加 `/v1/handoff-reports/get` |
| §5 记忆的证据链靠 `reason` 字段承载 | **`reason` 是 write-only 的**，`list` / `search` 都不返回，且上限 512 字符 | `reason` 仍写 provenance，但**可追踪标识放进记忆正文**（` [exp:<experiment_id>]`），用户可见 |
| §5 PreparedContext 用于上下文注入 | 未配置模型提供方时返回 **`status: empty`**（extract 422 / topic-memory 503 / profile disabled） | 不依赖它；恢复上下文靠 Handoff + Memory list，PreparedContext 状态在前端**如实展示** |
| §6 目录结构（`scripts/start-frontend.sh`、`seed-demo.sh`、`docker/docker-compose.yaml`） | — | 实际是 `scripts/dev-up.sh`、`dev-down.sh`、`start-backend.sh`、`start-powercontext.sh`、`init-db.py`、`e2e_demo.py`；compose 文件在 **`qoder/docker-compose.yml`**（根级），`docker/` 下是三个 Dockerfile + nginx.conf + seekdb 服务端 override |
| §7 `POWERCONTEXT_URL` 默认 8000 | 8000 与本机其他服务冲突 | 原生默认 **8010**；容器内 PowerContext 监听 8000，宿主映射到 8010 |
| §3 后端用 aiomysql/pymysql | embedded seekdb 通过 Unix socket 连接，aiomysql 在 PowerContext 侧有 pymysql 版本冲突 | LabTrace 后端**只用 PyMySQL**（每查询一连接 + `asyncio.to_thread`）；PowerContext 侧必须钉 `pymysql<1.2` |
| §3 前端用 shadcn/ui | 为几个基础组件引入整套 CLI + radix 依赖树不划算 | 手写 `components/ui/primitives.tsx`，风格与 shadcn 一致 |
| 未预料：容器化约束 | PowerContext **拒绝在未鉴权时绑定非回环地址**；`INFERENCE_*` 设成空字符串会导致**启动失败** | compose 固定 `ACCESS_MODE=enforced` + 必填 `POWERCONTEXT_AUTH_TOKEN`；推理配置改用可选 `env_file`（必须 unset，不能留空） |
| 未预料：embedded seekdb 的库 | embedded 实例**只有内置的 `test` 库** | `SEEKDB_DATABASE` 在 embedded 模式默认 `test`；独立服务端模式才用 `labtrace` |
| §11 阶段五完成 Qoder Sites 发布 | 需要账号权限 | **未完成**，方案见 [DEPLOYMENT.md §6](DEPLOYMENT.md) |
| 功能 6 科研知识关联图 | 按比赛要求排在核心功能验收之后 | **未实现** |

阶段计划的完成情况：**阶段一 ~ 阶段四全部完成并通过测试**；
阶段五除 Qoder Sites 发布外全部完成。验证记录见 [VERIFICATION.md](VERIFICATION.md)。

---

## 1. 仓库与赛题背景

- 比赛分支 `2026-competition-ecosystem` 为空脚手架，仅含 5 个赛题目录：`dify/ gaode/ minimax/ qoder/ stepfun/`，本赛题代码全部放入 `qoder/`。
- PowerContext 产品代码与文档位于 `2026-competition` 分支（基线 v1.2.0），本项目通过其 **HTTP API / Python Client SDK** 集成，不修改产品源码。
- seekdb 为 OceanBase 生态的向量/混合检索数据库，官方提供两种接入方式（详见 §4）。

## 2. 技术可行性验证结论（已在本机完成）

| 验证项 | 结果 |
| --- | --- |
| 嵌入式 seekdb（pylibseekdb 1.4.0.post1，WSL2 Ubuntu 22.04 / Python 3.12） | 通过。版本 `5.7.25-OceanBase seekdb-v1.4.0.0`，通过 Unix socket 连接 |
| seekdb `VECTOR(n)` 列 + HNSW 向量索引 DDL | 通过：`CREATE VECTOR INDEX ... WITH (distance=l2, type=hnsw)` |
| seekdb 全文索引与关键词检索 | 通过：`CREATE FULLTEXT INDEX ... WITH PARSER SPACE`，`MATCH(col) AGAINST (? IN NATURAL LANGUAGE MODE)` |
| seekdb 混合检索单 SQL | 通过：`WHERE MATCH(...) AGAINST(...) ORDER BY l2_distance(embedding, ?) APPROXIMATE LIMIT n` |
| ANN 检索 | 通过：`ORDER BY l2_distance(...) APPROXIMATE LIMIT n` |
| PowerContext v1.2.0 安装（`powercontext[cli,server,seekdb]`） | 通过（WSL2） |
| PowerContext HTTP API 契约 | 已从 `openapi/powercontext.yaml` 确认（见 §5） |

> Windows 原生不支持嵌入式 seekdb（`pylibseekdb` wheel 仅 manylinux）。因此**开发/运行环境为 WSL2 Ubuntu**，前端可在 Windows 侧通过 localhost 访问。

## 3. 技术栈

**前端**（`qoder/frontend/`）：React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui 风格组件 + Lucide Icons + React Router + TanStack Query。深色优先，Linear/Notion/Raycast 视觉风格。

**后端**（`qoder/backend/`）：Python 3.12 + FastAPI + Pydantic v2 + PyMuPDF（PDF 文本与页码提取）+ aiomysql/pymysql（seekdb MySQL 协议）+ httpx（PowerContext 与 OpenAI 兼容 API）。

**基础设施**：
- OceanBase seekdb —— 论文分块、向量/全文索引、实验记录（结构化 + 检索型数据）
- PowerContext Server（存储后端 `DATABASE_KIND=seekdb`）—— 研究状态、长期记忆、历史决策、跨会话 Handoff
- OpenAI 兼容 LLM API（可选）+ Embedding 服务（可选，未配置时回退为本地确定性哈希向量，保证导入/检索/实验记录等非生成功能可用）

## 4. seekdb 集成方式

后端支持两种模式，由 `SEEKDB_MODE` 环境变量切换：

| 模式 | 说明 | 适用场景 |
| --- | --- | --- |
| `embedded` | 后端进程内通过 `pylibseekdb.aopen(path)` 启动嵌入式实例，经 Unix socket 用 MySQL 协议连接 | 本机开发（WSL2/Linux/macOS）、单机部署 |
| `remote` | 通过 `SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE` 连接独立 OceanBase（`mysql+aoceanbase` 兼容协议，端口默认 2881） | Docker Compose、云端评审环境 |

### 表结构（LabTrace 自有数据）

- `lt_documents`：文档元数据（doc_id, project_id, title, topic, file_name, file_type, page_count, char_count, status, created_at）
- `lt_document_chunks`：论文分块 + 向量（chunk_id, doc_id, project_id, page_no, chunk_index, content, searchable_text, embedding VECTOR(n)），带 HNSW 向量索引 + FULLTEXT 索引
- `lt_experiments`：实验记录（experiment_id, project_id, name, objective, hypothesis, method, model_config JSON, dataset, result_summary, metrics JSON, issues, failure_reason, next_steps, status, created_at, updated_at），带 FULLTEXT 索引
- `lt_experiments_fts_view` / 复用同表 FULLTEXT 索引即可

所有查询使用参数化 SQL（`%s` 占位符），不拼接不可信输入。

### 检索流程

```
用户查询
  → 生成查询向量（Embedding 服务或本地哈希向量）
  → 混合检索单 SQL：MATCH(searchable_text) AGAINST(? IN NATURAL LANGUAGE MODE)
                    ORDER BY l2_distance(embedding, ?) APPROXIMATE LIMIT k
  → 返回 chunk（含 doc_id/page_no/原文片段）
  → 交由 LLM 生成带引用的回答（引用格式：论文名 + 页码 + 段落）
```

## 5. PowerContext 集成方式

通过 HTTP API（`POWERCONTEXT_URL`，默认 `http://127.0.0.1:8000`）访问运行中的 Server，端点已按 `openapi/powercontext.yaml` 核对：

| 能力 | 端点 | LabTrace 用途 |
| --- | --- | --- |
| 创建项目 Scope | `POST /v1/scopes`（title/summary/idempotency_key） | 每个研究项目一个 Scope，实现记忆隔离 |
| 捕获会话来源 | `POST /v1/sources/content`（scope_id/source_id/content/metadata） | 保存科研会话原文，作为记忆的证据链 |
| 写入记忆 | `POST /v1/memory/remember`（scope_id/kind/text/reason） | kind 使用自由标签：`research_profile` / `project_context` / `decision` / `failure` / `progress` / `next_action` |
| 检索记忆 | `POST /v1/memory/search`（scope_id/query/limit/mode） | AI 助手读取历史决策 |
| 列出记忆 | `POST /v1/memory/entries/list`（scope_id/include_inactive） | Memory 管理界面 |
| 修订记忆 | `POST /v1/memory/entries/revise`（scope_id/citation/kind/text/reason） | 用户纠正错误/过期记忆 |
| 停用记忆 | `POST /v1/memory/entries/retire`（scope_id/citation/reason） | 删除失效记忆（保留历史版本，可追溯来源） |
| 准备上下文 | `POST /v1/context/prepare`（scope_id/query/max_bytes） | AI 助手与"继续上次研究"的上下文注入 |
| 工作契约 | `POST /v1/work/contracts/create` | 登记当前研究任务目标与完成标准 |
| 保存进度（Handoff） | `POST /v1/work/handoffs/prepare-current` → `POST /v1/handoff/commit` | "保存本次研究进度"按钮 |
| 恢复进度 | `POST /v1/handoff/continue`（selection=latest） | 新会话"我上次研究到哪里了？" |
| 记录结果 | `POST /v1/work/outcomes/record` | 实验完成/受阻的真实边界记录 |
| 就绪/能力 | `GET /health/ready`、`GET /v1/capabilities` | 前端连接状态指示 |

**职责边界**：seekdb 保存可检索的原始证据（论文分块、实验记录）；PowerContext 保存研究状态与长期记忆（决策、失败、进度、下一步）。二者通过可追踪标识关联：记忆条目的 `reason` 字段与 Source `metadata` 中记录 `experiment_id` / `doc_id` / `chunk_id`，形成"记忆 ← 证据"链路。

## 6. 目录结构

```
qoder/
├── docs/                          # 全部交付文档（DEVELOPMENT_PLAN/ARCHITECTURE/SETUP/VERIFICATION/...）
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI 应用装配
│   │   ├── config.py              # 环境变量与配置校验
│   │   ├── db/                    # seekdb 连接池、DDL 初始化
│   │   ├── services/              # documents / retrieval / experiments / memory / assistant / reports / embeddings
│   │   ├── api/                   # 路由：documents / experiments / memory / chat / reports / projects / health
│   │   └── schemas.py             # Pydantic 请求/响应模型
│   ├── tests/                     # pytest 单元测试与端到端测试
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/                 # Overview / Library / Experiments / AIResearch / Memory / Reports / Settings
│   │   ├── components/            # UI 组件（shadcn 风格）
│   │   ├── lib/api.ts             # 后端 API 客户端
│   │   └── ...
│   └── package.json
├── sample-data/                   # 演示 A–D 用的样例论文（原创 Markdown）、实验 JSON、决策脚本
├── scripts/                       # start-backend.sh / start-frontend.sh / seed-demo.sh（WSL2 运行）
├── docker/                        # docker-compose.yaml（OceanBase + PowerContext + 后端）
├── .env.example
└── README.md
```

## 7. 环境变量（`.env.example`）

```
SEEKDB_MODE=embedded|remote
SEEKDB_PATH=...                     # embedded
SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE   # remote
EMBEDDING_DIMENSION=384
OPENAI_BASE_URL / OPENAI_API_KEY / CHAT_MODEL / EMBEDDING_MODEL   # 可选
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_TOKEN=                 # Server 启用鉴权时填写
```

敏感信息仅存于服务端环境变量，`.env` 不入库。

## 8. 阶段计划

**阶段一（本阶段）：规划与骨架** — 仓库分析、可行性验证、本计划文档、项目脚手架、seekdb DDL 初始化与连接层。

**阶段二：基础功能** — 前端导航与页面骨架；FastAPI 后端；论文上传与 PyMuPDF 提取（保留页码）；分块入 seekdb；关键词/向量/混合检索与引用展示；实验记录 CRUD 与 JSON 指标导入；Library / Experiments 页面。每模块完成即写测试并调试。

**阶段三：长期记忆** — PowerContext 连接与健康检查；按项目创建 Scope；记忆写入（6 类 kind）；记忆检索/列表/修订/停用；"保存本次研究进度"（Handoff prepare → commit）；新会话恢复（continue latest）；Memory 管理界面；项目间隔离验证。

**阶段四：AI 整合** — AI 科研助手（按问题类型路由 seekdb 论文证据 / seekdb 实验记录 / PowerContext 记忆 / 综合）；引用追踪与"知识来源"可解释性面板；无证据时明确说明无法确认；自动科研周报（按日期范围汇总，指标基于实际记录）。

**阶段五：测试与部署** — API 单元测试、seekdb 读写测试、PowerContext 持久化与跨会话恢复测试、端到端演示 A–D 脚本、前端构建测试、Docker Compose、Qoder Sites 发布前端与展示入口，补齐全部交付文档。

## 9. 演示案例（主题：Embodied Question Answering 与 3D Scene Memory）

`sample-data/` 内置**原创**样例文档（明确标注"示例数据，非真实科研结果"）：3 篇 EQA/3D-MEM 主题的原创 Markdown 论文摘要与正文段落、可核对的实验 JSON（含指标）、决策与任务进度脚本。演示 A（论文检索）、B（实验追踪）、C（跨会话记忆）、D（自动周报）均可重复执行，验收脚本位于 `scripts/` 与 `docs/VERIFICATION.md`。

## 10. 质量与安全约束

1. 参数化查询，禁止字符串拼接 SQL。
2. 上传文件校验类型（pdf/md/txt）、大小上限（默认 20MB）与文件名安全。
3. AI 生成内容与原始证据分离存储，回答附带引用来源。
4. 所有数据按 `project_id`（对应 PowerContext Scope）隔离。
5. 无 LLM API Key 时，导入、检索、实验记录、记忆读写仍可用；生成功能明确提示未配置。
6. 不使用模拟接口替代真实 seekdb / PowerContext 集成；无法验证的部分如实记录在 `docs/VERIFICATION.md`。

## 11. 待用户提供的外部资源

- 可选：OpenAI 兼容 LLM/Embedding API Key（用于生成式回答与语义向量）。未提供时使用本地确定性哈希向量 + 明确提示，核心检索链路仍真实经过 seekdb。
- Qoder Sites 发布账号（阶段五）。
- 如需云端 OceanBase 实例进行远程模式验证，请提供连接信息（否则使用 WSL2 嵌入式 seekdb + Docker Compose 本地验证）。
