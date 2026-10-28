# 技术集成说明：OceanBase seekdb 与 PowerContext

本文记录 LabTrace 实际使用的 seekdb SQL 特性与 PowerContext HTTP API，以及**在真实环境中验证出来的行为差异与版本约束**。

比赛要求"不允许假设某个 SDK 方法或数据库 API 一定存在，必须先阅读文档、确认版本，再编写集成代码"。
下面每一条结论都注明了是怎么确认的：读官方文档 / 读 OpenAPI schema / 在真实实例上跑 SQL / 在容器里探针验证。
凡是没有验证过的，都会明确写"未验证"。

**验证环境**

| 组件 | 版本 |
| --- | --- |
| OceanBase seekdb | `5.7.25-OceanBase seekdb-v1.4.0.0`（`SELECT VERSION()` 实测） |
| pylibseekdb | ≥ 1.4.0（embedded 模式） |
| PowerContext Server | 1.2.0 |
| Python | 3.12 |
| PyMySQL | ≥ 1.1（LabTrace 后端）；**< 1.2**（PowerContext 侧，见 §3.1） |
| 官方镜像 | `oceanbase/seekdb:latest` |

---

## 1. seekdb：向量能力

### 1.1 向量列与 HNSW 索引

```sql
CREATE TABLE IF NOT EXISTS lt_document_chunks (
    chunk_id VARCHAR(64) NOT NULL PRIMARY KEY,
    ...
    embedding VECTOR(384) NOT NULL,
    ...
);

CREATE VECTOR INDEX lt_chunks_vector_idx
    ON lt_document_chunks(embedding) WITH (distance=l2, type=hnsw);
```

**关键约束（实测）**

1. **`CREATE VECTOR INDEX` 没有 `IF NOT EXISTS`。**
   在一个已经有向量索引的列上重复执行，seekdb 返回：

   ```
   (1235, 'create vector index on column has vector index is not supported')
   ```

   注意这**不是**重名错误（1061），所以不能靠捕获重名错误来做幂等。
   `db/seekdb.py::_ensure_vector_index` 与 `scripts/init-db.py::index_exists` 都先查
   `information_schema.statistics` 判断存在性，再决定是否创建。

2. **向量索引会在 `information_schema.statistics` 里注册额外的索引名。**
   创建 `lt_chunks_vector_idx` 之后，实测该视图里除了它本身，还会出现
   `lt_chunks_vector_idx_index_id_table` 与 `lt_chunks_vector_idx_index_snapshot_data_table`
   两个条目，列名是内部的 `__vid_*` / `__type_*` / `__scn_*` / `__key_*`
   （下面每个 index_name 只摘一行，实际有多行）：

   ```
   index_name                                     column_name
   lt_chunks_vector_idx                           __vid_1793148778777695
   lt_chunks_vector_idx                           __type_23_1793148779303884
   lt_chunks_vector_idx_index_id_table            __scn_23_1793148779352077
   lt_chunks_vector_idx_index_snapshot_data_table chunk_id
   ```

   **它们不是用户表**：`SHOW TABLES` 与 `information_schema.tables` 里只有
   `lt_projects`、`lt_documents`、`lt_document_chunks`、`lt_experiments`、`lt_meta` 五张。
   全文索引同理，会注册出 `__doc_id_*` 与 `__word_segment_*` 列。
   这一点在做"表数量"断言或写清理脚本时需要注意，不要去 DROP 这些名字。

3. **`VECTOR(n)` 的维度是建表时固定的**，改维度必须重建表。所以
   `EMBEDDING_DIMENSION` 一旦定了、并且已经导入过数据，再改成别的维度就需要清空重来。
   `scripts/init-db.py` 提供 `--dimension` 参数，用于在新库上直接建成目标维度。

### 1.2 ANN 查询

```sql
SELECT c.chunk_id, ..., l2_distance(c.embedding, '[0.1,0.2,...]') AS l2_distance
FROM lt_document_chunks c JOIN lt_documents d ON d.doc_id = c.doc_id
WHERE c.project_id = %s
ORDER BY l2_distance APPROXIMATE
LIMIT 6;
```

- 语法是 `ORDER BY <距离表达式> APPROXIMATE LIMIT k`，**`APPROXIMATE` 必须紧跟在排序表达式之后**
- 距离函数用 `l2_distance`，与建索引时的 `distance=l2` 对应
- 向量以字面量形式出现在 SQL 里（seekdb 的向量参数不能用 `%s` 绑定），
  所以 `services/embeddings.py::format_vector` 先把浮点列表格式化成 `[v1,v2,...]`，
  且这些值全部来自本地计算或受信的 embedding API 响应，不是用户输入。
  其余所有条件仍然走 `%s` 参数化
- 加了 `WHERE c.project_id = %s` 之后 ANN 仍然是近似检索，命中数可能少于 `LIMIT`，
  这是预期行为（混合检索用另一路全文补齐）

### 1.3 距离到分数的换算

`retrieval.py` 把 L2 距离换算成 0–1 的相似度便于展示：

```python
score = 1.0 / (1.0 + l2_distance)
```

同时原始 `l2_distance` 与 `fts_score` 都保留在响应里，前端可解释性面板能看到真实数值，
不做美化。

---

## 2. seekdb：全文能力

### 2.1 建索引

```sql
CREATE FULLTEXT INDEX lt_chunks_ft_idx
    ON lt_document_chunks(searchable_text) WITH PARSER ik;

CREATE FULLTEXT INDEX lt_experiments_ft_idx
    ON lt_experiments(searchable_text) WITH PARSER ik;
```

可选 parser：`ik` / `ngram` / `space` / `beng`。
**`WITH PARSER chinese` 是无效的**（早期试过，seekdb 不接受）。

### 2.2 parser 选择：实测对比

LabTrace 的语料是"中文研究笔记 + 英文技术术语"，parser 选错会直接导致中文检索返回 0 条。
在真实 seekdb 1.4.0 上用 6 个中文查询逐一测试四种 parser：

| parser | 6 个中文查询的命中情况 | 结论 |
| --- | --- | --- |
| `space` | **0 / 6** | 只按空格切词，完全不切中文，不可用 |
| `beng` | **0 / 6** | 同上，不可用 |
| `ngram` | 6 / 6 | 可用，但英文短语会被过度切分、over-match |
| `ik` | 6 / 6 | **可用，中文分词 + 英文保持整词，精度最好 → 默认值** |

所以 `SEEKDB_FULLTEXT_PARSER` 默认 `ik`，允许改成 `ngram`。

### 2.3 ik 不过滤停用词（重要陷阱）

`ik` **不会**过滤中文停用词。实测：查询单字 `的` 会命中语料里几乎每一个分块，
`fts_score ≈ 0.49`；而真正的内容词（如 `体素`、`记忆`）分数在 `2.1 – 4.7` 之间。

影响：
- **排序仍然是对的**——因为停用词分数远低于内容词，`ORDER BY fts_score DESC` 之后
  相关内容排在前面
- 但**用裸虚词做探针会得到"命中很多"的假象**。写测试或做演示时，
  关键词查询要用内容词，不要用 `的`/`了`/`是` 之类来验证"检索有没有工作"

这一点在 `.env.example` 与 `db/schema.sql` 的注释里都写明了。

### 2.4 parser 变更时重建索引

parser 是建索引时固定进索引定义的，**`information_schema` 查不出某个全文索引用的是哪个 parser**。
所以 LabTrace 自己记一份：

```sql
CREATE TABLE lt_meta (
    meta_key VARCHAR(64) NOT NULL PRIMARY KEY,
    meta_value VARCHAR(255) NOT NULL,
    updated_at DATETIME NOT NULL
);

INSERT INTO lt_meta (meta_key, meta_value, updated_at) VALUES ('fulltext_parser','IK', ...)
ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value), updated_at = VALUES(updated_at);
```

`db/seekdb.py::_ensure_fulltext_indexes` 在启动时比对 `lt_meta` 里的值与当前配置：
不一致就 `DROP INDEX` 两个全文索引再按新 parser 重建。
`recorded is None`（老库还没记过）也走重建路径，因为那些索引是用旧默认值建的、无法内省。

### 2.5 查询

```sql
SELECT ..., MATCH(c.searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS fts_score
FROM lt_document_chunks c JOIN lt_documents d ON d.doc_id = c.doc_id
WHERE c.project_id = %s
  AND MATCH(c.searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE)
ORDER BY fts_score DESC, c.chunk_index
LIMIT 6;
```

- `MATCH ... AGAINST` 需要在 SELECT 与 WHERE 各写一次（一次取分数、一次做过滤），
  因此参数元组里 query 出现两次，**顺序必须严格对应 SQL 文本中占位符的顺序**
  （`retrieval.py::_keyword_leg` 有注释说明）
- 用 `IN NATURAL LANGUAGE MODE`，不用 `IN BOOLEAN MODE`：自然语言模式自带相关度打分，
  正是要的东西
- 实验检索复用同样语法，只是表换成 `lt_experiments`、索引换成 `lt_experiments_ft_idx`

### 2.6 混合检索：Reciprocal Rank Fusion

两路各取 top-k，再融合：

```
score(doc) = Σ_legs  1 / (RRF_K + rank_in_leg)      RRF_K = 60
```

- 同一条分块在两路都命中时，`matched_by` 合并成 `["fulltext", "vector"]`
- 只被一路命中时保留该路的 `matched_by`，并且**保留它原本的 `fts_score` 或 `l2_distance`**，
  另一路分数为 `null`（不伪造 0）
- 响应里的 `sql_mode` 字段会把本次实际用到的 SQL 特性原样写出来，例如：

  ```
  seekdb FULLTEXT (MATCH...AGAINST) + VECTOR ANN (l2_distance APPROXIMATE), RRF fusion
  ```

  这是为了在演示时能一眼确认"检索真的经过了 seekdb"，而不是接口里返回一个写死的结果。

---

## 3. seekdb：部署形态

### 3.1 embedded（pylibseekdb）

```python
import pylibseekdb
instance = await pylibseekdb.aopen("/data/labtrace-seekdb")
options = instance.connection_options()
# 实测输出：{'user': 'root', 'unix_socket': '/tmp/pylibseekdb-uds-10-XXXX/run/sql.sock'}
```

- 只支持 **Linux / macOS**，`requirements.txt` 里用环境标记限定：
  `pylibseekdb>=1.4.0; sys_platform == 'linux' or sys_platform == 'darwin'`
- 拿到 `unix_socket` 后仍然用 **PyMySQL** 连接（`pymysql.connect(unix_socket=...)`），
  不需要额外的 DB-API 驱动
- **embedded 实例只有内置的 `test` 数据库**，没有 `mysql`/`information_schema` 之外的用户库。
  所以 `SEEKDB_DATABASE` 在 embedded 模式下默认 `test`。
  一开始按直觉写成 `labtrace` 会得到：

  ```
  (1049, "Unknown database 'labtrace'")
  ```

  PowerContext 的 embedded seekdb 用的也是同一个 `test` 库（两套数据在同一个库里的不同表，
  表名前缀不同，互不干扰）
- **不需要额外系统库。** 探针容器（`scratch/probe_seekdb.sh`）在干净的 `python:3.12-slim`
  里只 `pip install pylibseekdb pymysql` 就跑通了 `aopen` + `SELECT VERSION()` +
  `VECTOR(4)` 建表 + ANN 查询，输出 `OK-no-libaio-package`。
  所以 `Dockerfile.backend` / `Dockerfile.powercontext` 里**没有 apt 层**。
  > 踩坑记录：最初照抄了别处"seekdb 需要 libaio"的说法写了 `apt-get install -y libaio1`，
  > 构建直接失败退出码 100——因为 `python:3.12-slim` 现在是 **Debian 13 trixie**，
  > 包名已经改成 `libaio1t64`。与其改包名，不如先探针验证到底需不需要，结果是不需要，
  > 于是把整个 apt 层删掉，镜像更小也更稳。

### 3.2 remote（独立 seekdb 服务端）

官方镜像 `oceanbase/seekdb:latest`，实测行为：

- entrypoint 是 `/root/start.sh`，容器内监听 `127.0.0.1:2881`，镜像自带 mysql 客户端
- 支持的环境变量：`ROOT_PASSWORD`、`SEEKDB_DATABASE`、**`INIT_SCRIPTS_PATH`**、
  `MEMORY_LIMIT`、`DATAFILE_SIZE`、`DATAFILE_MAXSIZE`、`LOG_DISK_SIZE`、`CPU_COUNT`
- `INIT_SCRIPTS_PATH` 指向的目录里所有 `*.sql` 会在**首次初始化**时按文件名顺序执行，
  并且带 `-D$SEEKDB_DATABASE`。`docker/docker-compose.seekdb-server.yml` 就是把
  `qoder/db` 只读挂到 `/init-scripts`，于是 `db/schema.sql` 会自动建库建表建索引。
  容器日志实测：

  ```
  Database labtrace created.
  Executing /init-scripts/schema.sql...
  Finished executing /init-scripts/schema.sql.
  ```

  > 注意"首次初始化"：数据卷已存在时不会再跑 init 脚本。改了 schema 需要
  > `docker compose down -v` 或手动执行 `scripts/init-db.py`。

- 健康检查用镜像自带的 mysql 客户端，密码走 `MYSQL_PWD` 环境变量而不是命令行
  （避免出现在 `ps` 里）：

  ```yaml
  test: ["CMD-SHELL", "MYSQL_PWD=\"$$ROOT_PASSWORD\" mysql -h127.0.0.1 -P2881 -uroot -e 'SELECT 1'"]
  ```

  `$$` 是 Compose 的转义，让变量在容器内展开而不是在宿主机插值。

后端切到 remote 只需 `SEEKDB_MODE=remote` + `SEEKDB_HOST/PORT/USER/PASSWORD/DATABASE`，
`db/seekdb.py` 的连接分支会走 TCP，其余代码完全不变。

**PowerContext 侧始终用 embedded**：`POWERCONTEXT_SERVER_DATABASE_KIND=seekdb` 是
基于路径的 embedded 存储，PowerContext 1.2.0 没有暴露"连远端 seekdb 服务端"的配置项。
所以即使 LabTrace 后端连的是独立 seekdb 服务端，PowerContext 仍然用自己的 embedded 实例。
这两个实例互不相关，是设计如此，不是配置遗漏。

### 3.3 `scripts/init-db.py`

给"已经有一个空的 seekdb 服务端、但没有走 init 脚本"的场景用，从 `db/schema.sql` 建库建表建索引：

- `split_statements()` 去掉 `--` 注释行、按 `;` 切分
- `apply_options()` 支持覆盖：丢掉 `USE` 语句、重写库名、重写 `VECTOR(n)` 维度、
  重写 `WITH PARSER x`、重写 `lt_meta` 里的 `'fulltext_parser','X'` 字面量
  —— 保证覆盖后索引定义与元数据记录一致
- **幂等**：`ALREADY_EXISTS_ERRORS = {1007, 1050, 1061}`（库已存在 / 表已存在 / 索引名已存在）
  被当作"已初始化"而不是失败，打印 `exists:` 后继续；向量与全文索引额外做前置存在性检查
  （因为 §1.1 里的 1235 错误）
- `CREATE DATABASE` 之后立刻 `connection.select_db(database)`。
  因为 `USE` 被 `apply_options` 丢掉了，不 select 会得到 `(1046, 'No database selected')`
- 支持 `--dry-run`（只打印将执行的语句数、维度、parser）
- 已验证：对已初始化的库重复执行全部输出 `exists:`；对一个全新库名执行能建出全部表与索引

---

## 4. PowerContext Server 1.2.0

### 4.1 LabTrace 实际调用的端点

全部在 `services/powercontext.py` 中封装，`services/memory.py` 是唯一调用方。

| 端点 | 用途 |
| --- | --- |
| `GET /health/live`、`GET /health/ready` | 健康检查，`/api/health` 直接透出 |
| `GET /v1/capabilities` | 能力探测，Settings 页展示 |
| `POST /v1/scopes` | 创建项目时建 Scope（带 `idempotency_key`） |
| `GET /v1/scopes/{scope_id}` | 读取 Scope |
| `POST /v1/sources/content` | 捕获研究会话原文 |
| `POST /v1/memory/remember` | 写入一条记忆 |
| `POST /v1/memory/search` | 语义/全文检索记忆 |
| `POST /v1/memory/entries/list` | 列出记忆（`include_inactive` 控制是否含已停用） |
| `POST /v1/memory/entries/get` | 按精确引用读一条 |
| `POST /v1/memory/entries/revise` | 修订（产生新版本） |
| `POST /v1/memory/entries/retire` | 停用 |
| `POST /v1/context/prepare` | 打包 PreparedContext |
| `POST /v1/handoff/finalize` | draft → prepared handoff |
| `POST /v1/handoff/commit` | prepared → committed，返回 `reference` |
| `POST /v1/handoff/continue` | 新会话读取并 resolve |
| `POST /v1/handoff-reports/get` | 交接报告 |

### 4.2 鉴权与绑定地址（容器化踩坑）

`ACCESS_MODE` 是唯一官方开关，取值 `disabled` | `enforced`。
静态 Bearer Token 通过 `POWERCONTEXT_SERVER_AUTH_TOKEN` 配置，映射到内置 admin principal。

**坑：容器必须绑定 `0.0.0.0`（非回环地址），而 PowerContext 拒绝在未启用鉴权时绑定非回环地址：**

```
Invalid value for --host: refusing to bind an unauthenticated Server to a non-loopback address
```

所以 `docker-compose.yml` 里固定 `ACCESS_MODE=enforced` + **必填**的 `POWERCONTEXT_AUTH_TOKEN`：

```yaml
POWERCONTEXT_SERVER_ACCESS_MODE: enforced
POWERCONTEXT_SERVER_AUTH_TOKEN: ${POWERCONTEXT_AUTH_TOKEN:?set POWERCONTEXT_AUTH_TOKEN in qoder/.env or the shell}
```

- `${VAR:?msg}` 让 Compose 在缺变量时**立刻失败并给出提示**，而不是静默用空值启动
- 同一个 token 也传给后端作为 `POWERCONTEXT_TOKEN`，后端用它发 `Authorization: Bearer`
- token 从不写死在仓库里；`.env` 已被 `.gitignore` 排除
- 原生开发脚本（`scripts/dev-up.sh`）绑定 `127.0.0.1`，因此可以用 `ACCESS_MODE=disabled`
- 另有一个 `ALLOW_UNAUTHENTICATED_NON_LOOPBACK` 开关可以强行放开，
  但 LabTrace **不使用**它——公开演示环境不该跑无鉴权服务

> Compose 的另一个坑：**每个子命令都会重新插值**。所以 `up` 成功之后，
> 直接跑 `docker compose ps` 会因为找不到 `POWERCONTEXT_AUTH_TOKEN` 而报
> "required variable is missing"。解决办法是把变量放进 `qoder/.env`
> （compose 会自动读取同目录的 `.env`），或在每条命令前 export。

### 4.3 推理配置：空值会导致启动失败

PowerContext 的推理配置形如 `INFERENCE_GENERATION_MODEL=provider:model-name`（Pydantic AI），
凭据从 `OPENAI_API_KEY` 等标准变量读取。

**坑：把 `POWERCONTEXT_SERVER_INFERENCE_GENERATION_MODEL` 设成空字符串会让容器直接崩溃：**

```
inference.generation_model — Value error, inference identifiers must not be empty
```

所以这些变量必须**完全不设置**，而不是设置为空。`docker-compose.yml` 因此不写这些 env，
改用一个可选的 `env_file`：

```yaml
env_file:
  - path: docker/powercontext-inference.env
    required: false
```

模板见 `docker/powercontext-inference.env.example`，里面说明了配好之后能解锁什么、
不配时各个端点的实际行为（见 §4.6）。

其他相关配置（读 `pc-sdk/docs/zh/docs/operate/configuration.md` 确认）：
- 定时抽取还需要 `RUNTIME_SCHEDULE_SECONDS`
- 抽取 profile：`coding` | `conversation`
- 嵌入需要 `EMBEDDING_MODEL` + `PROFILE_ID` + `DIMENSION` 三者齐备

### 4.4 Memory：引用、版本、修订冲突

`MemoryEntry` 的必填字段（读 OpenAPI schema `pc-sdk/openapi/powercontext.yaml` 确认）：
`citation`、`version`、`kind`、`text`、`state`、`source_refs`、`artifact_refs`。

**`kind` 是自由字符串**，不是枚举，所以 LabTrace 的六类
（`research_profile` / `project_context` / `decision` / `failure` / `progress` / `next_action`）
可以直接用，PowerContext 不会拒绝；`services/memory.py::write_memory` 自己校验白名单，
避免拼写错误静默产生第七类。

**`MemoryCitation` 是三元组**，每次变更操作都必须原样回传：

```json
{ "memory_ref": "...", "entry_id": "...", "entry_version_id": "..." }
```

修订会返回新的 `entry_version_id` 与递增的 `version`；
**用过期的引用去 revise/retire 会得到 `revision_conflict`（HTTP 409）**。
`_retry_on_stale_revision` 的处理是：重新 `list_entries` 读取当前引用，只有 entry_version_id 未改变时才刷新 artifact revision 重试；目标内容已被修订 / 停用则直接返回冲突；
仍失败就把 409 如实抛给前端，让用户刷新后重试。不做静默覆盖。

**`RememberMemoryRequest.reason` 上限 512 字符，而且是 write-only 的**——
`list` 与 `search` 都不返回它。两个后果：

1. `_reason()` 拼 provenance 字符串时会先保住人类可读部分，evidence JSON 只在总长 ≤ 512 时才追加
2. 因为用户看不到 `reason`，**可追踪标识必须放进 `text`**。
   `sync_experiment_to_memory` 因此给每条记忆正文追加 ` [exp:<experiment_id>]`，
   这样 Memory 界面能直接看到这条记忆来自哪条 seekdb 实验记录

### 4.5 Memory search 走的是全文检索

`POST /v1/memory/search` 返回体里带 `mode` 字段，实测当前部署返回 `mode: "fts"`
（没有配置嵌入模型，所以不是语义检索）。

后果：**用自然语言长句去 search 可能召回很少甚至为 0**。这不是 bug，是能力降级。
LabTrace 的处理是"search + list 双路"：
`restore_progress` 与助手回答都会同时调 `entries/list`（按 kind 分组的全量）与 `search`，
把 list 作为兜底，`data_sources` 里两者分别标注为
`powercontext.memory_list` 与 `powercontext.memory_search`，前端能看到本次到底用了哪一路。

这是**有意的设计**，不是绕过 PowerContext。

### 4.6 PreparedContext 为空：未配置模型提供方（如实说明）

`PreparedContext` 的必填字段是 `[schema, status, content, content_bytes]`，
`status` 枚举为 `[ready, empty]`。OpenAPI 明确说明 **`empty` 是正常状态**。

在当前部署（未配置任何模型提供方）下，实测三个 flush 端点的行为：

| 端点 | 实测响应 |
| --- | --- |
| `POST /v1/memory/flush` | **422** `capability_not_supported (extract)` |
| `POST /v1/topic-memory/flush` | **503** |
| `POST /v1/profile/flush` | `{"status": "disabled"}` |

因此 `/v1/context/prepare` 返回 `status: "empty"`。
自动记忆抽取（extract）、Topic Memory、Profile 这三条能力**需要模型提供方才会启用**。

LabTrace 的应对：
- **不依赖 extract**。所有记忆都通过显式 `/v1/memory/remember` 写入，
  由用户点"保存本次研究进度"或"把实验写入记忆"触发，写入内容全部来自
  seekdb 记录或用户输入，不做模型猜测
- `restore_progress` 里 `prepare_research_context` 失败或返回 empty 都不影响整体结果，
  Handoff + Memory list 已经能完整恢复上下文
- 前端 Memory 页面的恢复面板**如实展示 PreparedContext 的状态**，
  empty 时就写 empty，不假装有内容

> **未验证项**：配好 `POWERCONTEXT_SERVER_INFERENCE_GENERATION_MODEL` + `OPENAI_API_KEY`
> + `EMBEDDING_MODEL/PROFILE_ID/DIMENSION` 之后，extract / Topic Memory / Profile /
> 非空 PreparedContext 应该能启用，但**本次开发全程没有模型 API Key，这条链路没有实测过**。
> `docker/powercontext-inference.env.example` 给出了配置项，欢迎补充验证。

### 4.7 Handoff：跨会话接续的完整链路

比赛核心要求是"新会话必须能恢复真实保存的上下文"，且"不允许只依靠浏览器 localStorage"。
LabTrace 用 PowerContext 官方的 Handoff 能力实现，四步：

```
1. draft（LabTrace 组装）
   {
     objective:   "本次研究目标"（≤ 8000 字符）
     state:       [{ text, citations: [source_citation] }, ...]（≤ 64 条）
     disposition: "continuable" | "blocked"   ← 有 open_questions 但没有 next_steps 时判 blocked
     next_action: { text, citations }
     omissions:   [{ text, citations }, ...]（≤ 64 条）
   }
2. POST /v1/handoff/finalize  → prepared handoff
3. POST /v1/handoff/commit    → { status: "committed", reference: {...} }
4. POST /v1/handoff/continue (selection="latest")  → resolved + content + evidence_checks
```

**每条 statement 都带 citation，指向第 1 步捕获的那个 Source**
（`source_citation(source_ref)` 生成 `{kind: "source", source_ref: {name, source_id}}`）。
`CommittedHandoff` 的必填字段是 `[reference, content, source_refs, artifact_refs]`，
实测 commit 返回：

```json
{"status": "committed",
 "reference": {"family": "handoff", "artifact_id": "handoff", "revision": 1}}
```

新会话 `continue` 之后 `status` 变为 `resolved`，`content` 里能拿回
objective / state / next_action / omissions，`evidence_checks` 给出证据校验结果。

**降级**：commit 失败时 `save_progress` 不抛异常，而是记
`handoff: {status: "failed", error: ...}` 并 warning——
记忆已经写进去了，Source 也捕获了，用户的研究状态不会因为 Handoff 这一步失败而丢失。
`restore_progress` 同理，三个来源任一失败都降级为部分结果 + 错误信息。

### 4.8 `pymysql<1.2` 硬约束

PowerContext 1.2.0 的 seekdb 驱动依赖 **aiomysql 0.3.2**，它调用
`pymysql.converters.escape_bytes_prefixed`。这个函数在 **pymysql 1.2 里被替换成了一个哨兵字符串**，
于是所有 bytes 类型参数都会崩。

所以：

```dockerfile
RUN pip install --user "powercontext[cli,server,seekdb]==1.2.0" "pymysql<1.2"
```

```bash
uv tool install --force --with 'pymysql<1.2' 'powercontext[cli,server,seekdb]==1.2.0'
```

`Dockerfile.powercontext` 与 `scripts/dev-up.sh` 的错误提示里都写了这条约束和原因。
**LabTrace 后端自己不受影响**（它直接用 PyMySQL，不用 aiomysql），
`backend/requirements.txt` 里是 `pymysql>=1.1`。

---

## 5. LLM 与 Embedding

### 5.1 可选的 OpenAI 兼容接口

```
OPENAI_BASE_URL + OPENAI_API_KEY + CHAT_MODEL       → 启用生成式回答
OPENAI_BASE_URL + OPENAI_API_KEY + EMBEDDING_MODEL  → 启用真实语义向量
```

`config.py` 里三个值默认都是 `""`，`llm_enabled` / `embedding_api_enabled`
要求**全部非空**才为真。所以环境变量设成空字符串是安全的（等价于未配置），
这一点与 PowerContext 的行为相反（§4.3），不要混淆。

比赛要求"没有配置大模型 API 时，仍应可以执行资料导入、数据库检索和实验记录等非生成式基础功能"——
LabTrace 全部 27 个 live 测试与 e2e 演示都是在**未配置任何 LLM** 的情况下跑通的。

### 5.2 嵌入维度校验

`_embed_remote` 会逐条检查返回向量长度是否等于 `EMBEDDING_DIMENSION`，
不一致直接抛 `EmbeddingError` 并说明"模型返回 N 维，配置是 M 维"。
宁可失败也不静默写入错误维度——因为 `VECTOR(n)` 列的维度是固定的（§1.1）。

配置远程嵌入后，服务故障、批次数量 / 顺序 / 维度错误或非有限数值都会返回 EmbeddingError（HTTP 503），不写入哈希向量，避免污染同一索引。未配置 API 时才使用确定性哈希。

### 5.3 `local-hash-fallback` 是什么

```python
token → blake2b(token, 8 bytes) → index = int(digest[:4]) % dim, sign = ±1
vector[index] += sign → L2 归一化
```

分词规则：`[a-zA-Z0-9]+` 连续串，或单个 CJK 字符。

- **确定性**：同样输入永远得到同样向量，测试可复现
- **词袋式**：共享 token 的文本会靠近，所以"关键词式的向量召回"仍然有效
- **不是语义模型**：同义改写不会靠近，跨语言不会靠近

这一点在 `/api/health`（`embedding.provider`）、Settings 页面、README 与本文都如实说明，
**不把它包装成语义检索**。配置 `EMBEDDING_MODEL` 后自动切换，无需改代码或改表结构
。切换提供方或模型后必须删除原文档并重新导入，维度相同也不代表向量空间相同。

---

## 6. 集成层面的安全约束

| 要求 | 实现 |
| --- | --- |
| 凭据只在服务端环境变量 | 前端只调 `/api/*`；`.env`、`docker/*.env`、`scripts/powercontext.env` 全部在 `.gitignore` 中，只提交 `.example` |
| 参数化查询 | 所有 SQL 用 `%s` 占位；唯一的字面量拼接是向量（本地计算/受信 API 返回值）与索引名/表名/parser（枚举白名单），均不含用户输入 |
| 上传校验 | 扩展名白名单 + MIME + `LABTRACE_MAX_UPLOAD_MB`；只有 PDF 走 PyMuPDF |
| AI 输出与原始证据分离 | seekdb 只存原文与用户录入字段；模型生成的段落只在响应中返回；PowerContext 记忆条目带 Source 引用，可回溯到原文 |
| 项目隔离 | seekdb 每表带 `project_id` 索引列并出现在所有 WHERE；PowerContext 每项目一个 Scope |
| 服务状态可见 | `/api/health` 聚合四个子系统状态；`SeekDBError`→503、`PowerContextError`→502 带原始信息片段 |
