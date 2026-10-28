> Windows 可先使用 `scripts/start.ps1`；本轮最新验证见 `VERIFICATION.md`，提交步骤见 `SUBMISSION.md`。

# 环境准备与安装

LabTrace 有三条安装路径，按推荐程度排列：

| 路径 | 适合 | seekdb 形态 | 前置条件 |
| --- | --- | --- | --- |
| **A. Docker Compose（embedded）** | 快速体验、评审 | 后端容器内 embedded seekdb | Docker + Compose v2，约 6 GB 内存 |
| **B. Docker Compose（独立 seekdb 服务端）** | 想看真实 OceanBase 服务端 | 官方 `oceanbase/seekdb` 容器 + `SEEKDB_MODE=remote` | 同上，约 8 GB 内存 |
| **C. 原生开发环境** | 二次开发、改代码 | embedded seekdb（`pylibseekdb`） | Linux / macOS / **WSL2**，Python 3.12，Node 20+ |

> **原生 Windows 不支持路径 C**：`pylibseekdb` 只提供 Linux / macOS 的 embedded 运行时。
> Windows 上请用 WSL2（本文以 WSL2 Ubuntu 22.04 为例）或 Docker Desktop。

**路径 A 与 B 已在本机完整验证**（三个容器 healthy、27 个 live 测试通过、e2e 演示全绿），
验证记录见 [VERIFICATION.md](VERIFICATION.md)。路径 C 是本项目的日常开发环境，
121 个单元测试 + 27 个 live 测试都是在它上面跑通的。

---

## 0. 通用前置说明

### 0.1 端口约定

| 服务 | 默认端口 | 变量 |
| --- | --- | --- |
| 前端 | 5173 | `LABTRACE_WEB_PORT` |
| LabTrace API | 8100 | `LABTRACE_API_PORT` |
| PowerContext Server | 8010（原生）/ 8010（容器映射） | `POWERCONTEXT_PORT` |
| seekdb 服务端（仅路径 B） | 2881 | `SEEKDB_SERVER_PORT` |

所有容器端口都绑定在 `127.0.0.1`，不对公网暴露。
如果要同时跑两套（例如原生 + 容器），把容器那套的端口改掉即可，例如：

```bash
LABTRACE_WEB_PORT=15173 LABTRACE_API_PORT=18100 POWERCONTEXT_PORT=18010 SEEKDB_SERVER_PORT=12881 \
  docker compose up -d
```

### 0.2 敏感信息

`.env`、`docker/*.env`、`scripts/powercontext.env` 都在 `qoder/.gitignore` 里，**不会被提交**。
仓库内只有 `.env.example` 与 `docker/powercontext-inference.env.example` 两个模板。
API Key、数据库密码、PowerContext Token 只通过环境变量注入。

### 0.3 国内网络镜像

拉不到官方源时，在 `qoder/.env` 里配置（Dockerfile 与 compose 的默认值仍指向官方源）：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY=https://registry.npmmirror.com
PYTHON_BASE_IMAGE=docker.1ms.run/library/python:3.12-slim
NODE_BASE_IMAGE=docker.1ms.run/library/node:22-alpine
NGINX_BASE_IMAGE=docker.1ms.run/library/nginx:1.27-alpine
SEEKDB_IMAGE=docker.1ms.run/oceanbase/seekdb:latest
```

> 本项目的验证过程中 docker.io 不可达，`docker.m.daocloud.io` 会卡住（日志停在 308 字节不动），
> 最终用 `docker.1ms.run` 成功。这是环境情况，不是配置要求。

---

## A. Docker Compose（embedded seekdb）

### A.1 步骤

```bash
cd qoder
cp .env.example .env

# 必填。PowerContext 拒绝在未启用鉴权时绑定非回环地址，而容器必须绑定 0.0.0.0。
# 生成一个随机 token：
echo "POWERCONTEXT_AUTH_TOKEN=$(openssl rand -hex 18)" >> .env

docker compose up -d --build
```

首次构建约 5–10 分钟（要装 PowerContext 1.2.0、pylibseekdb、npm 依赖并构建前端）。
embedded seekdb 首次启动需要初始化数据文件，PowerContext 容器的健康检查
`start-period` 设了 60 秒、重试 18 次，请耐心等。

### A.2 确认

```bash
docker compose ps
# labtrace-powercontext  running (healthy)
# labtrace-backend       running (healthy)
# labtrace-frontend      running (healthy)

curl -s http://127.0.0.1:8100/api/health | python -m json.tool
```

期望输出（本机实测）：

```json
{
  "status": "ok",
  "seekdb": {
    "connected": true,
    "mode": "embedded",
    "version": "5.7.25-OceanBase seekdb-v1.4.0.0"
  },
  "powercontext": {
    "url": "http://powercontext:8000",
    "reachable": true,
    "ready": true
  },
  "llm": { "configured": false },
  "embedding": { "provider": "local-hash-fallback", "dimension": 384 }
}
```

打开 <http://127.0.0.1:5173>，Settings 页应显示同样的四组状态。

### A.3 跑验收演示

```bash
docker compose exec backend python -c "print('ok')"     # 容器内自检
# 从宿主机跑（需要宿主机有 Python + httpx）：
pip install httpx
python scripts/e2e_demo.py --api http://127.0.0.1:8100 --keep
```

### A.4 停止与清理

```bash
docker compose down          # 停容器，保留数据卷
docker compose down -v       # 连数据卷一起删（powercontext-data, labtrace-seekdb-data）
```

数据卷：`powercontext-data`（PowerContext 的 embedded seekdb）、
`labtrace-seekdb-data`（LabTrace 的 embedded seekdb）。

### A.5 常见问题

**`required variable POWERCONTEXT_AUTH_TOKEN is missing`（明明 up 成功了）**
Compose 的每个子命令都会重新插值。把 token 写进 `qoder/.env`（compose 自动读取），
或者每条命令前都 export。

**PowerContext 容器反复重启，日志里有 `inference identifiers must not be empty`**
不要把 `POWERCONTEXT_SERVER_INFERENCE_*` 设成空字符串——必须完全不设置。
检查 `.env` 与 `docker/powercontext-inference.env` 里有没有 `XXX=` 这样的空赋值行。

**后端容器报 `(1049, "Unknown database 'labtrace'")`**
embedded seekdb 只有内置的 `test` 库。compose 默认已是
`SEEKDB_EMBEDDED_DATABASE:-test`；如果你在 `.env` 里覆盖成了别的值，改回 `test`。

**后端容器报 `(1235, 'create vector index on column has vector index is not supported')`**
说明数据卷里已经有向量索引了。这是启动时索引检查应当拦下的情况；
如果确实撞到，`docker compose down -v` 重来，或改用路径 B 的 `scripts/init-db.py`
（它对 1235 做了前置存在性检查）。

**前端 502 / `/api` 打不开**
`docker/nginx.conf` 里 `proxy_pass http://backend:8100`，确认 backend 容器 healthy：
`docker compose logs backend`。

---

## B. Docker Compose + 独立 OceanBase seekdb 服务端

这条路径用官方 `oceanbase/seekdb` 镜像跑一个真实的 seekdb 服务端，
后端切到 `SEEKDB_MODE=remote`，用 `db/schema.sql` 通过 `INIT_SCRIPTS_PATH` 自动初始化。

> PowerContext 仍然用它自己的 embedded seekdb 存储——
> PowerContext 1.2.0 的 `DATABASE_KIND=seekdb` 是路径式的 embedded 存储，
> 没有"连远端 seekdb 服务端"的配置项。这是设计如此，不是配置遗漏。

### B.1 步骤

```bash
cd qoder
cp .env.example .env
echo "POWERCONTEXT_AUTH_TOKEN=$(openssl rand -hex 18)" >> .env

# 建议显式设置，避免和已有的 2881 端口冲突
cat >> .env <<'EOF'
SEEKDB_ROOT_PASSWORD=labtrace
SEEKDB_MEMORY_LIMIT=4G
SEEKDB_DATAFILE_SIZE=2G
SEEKDB_LOG_DISK_SIZE=4G
EOF

docker compose -f docker-compose.yml -f docker/docker-compose.seekdb-server.yml up -d --build
```

OceanBase 服务端首次初始化需要几分钟，healthcheck 用镜像自带的 mysql 客户端探活，
backend 有 `depends_on: seekdb: condition: service_healthy`，会等它就绪。

### B.2 确认初始化脚本真的跑了

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.seekdb-server.yml logs seekdb \
  | grep -E "Database|init-scripts"
```

本机实测输出：

```
Database labtrace created.
Executing /init-scripts/schema.sql...
Finished executing /init-scripts/schema.sql.
```

核对表与索引：

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.seekdb-server.yml \
  exec seekdb bash -c 'MYSQL_PWD="$ROOT_PASSWORD" mysql -h127.0.0.1 -P2881 -uroot -Dlabtrace \
  -e "SHOW TABLES; SELECT meta_key, meta_value FROM lt_meta;"'
```

期望看到 `lt_projects`、`lt_documents`、`lt_document_chunks`、`lt_experiments`、`lt_meta`，
期望看到 `lt_projects`、`lt_documents`、`lt_document_chunks`、`lt_experiments`、`lt_meta` 五张表，
以及 `lt_meta` 里的一行 `fulltext_parser | IK`。

再核对索引（向量索引与全文索引没有 `IF NOT EXISTS`，靠这份查询确认它们建成了）：

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.seekdb-server.yml \
  exec seekdb bash -c 'MYSQL_PWD="$ROOT_PASSWORD" mysql -h127.0.0.1 -P2881 -uroot \
  -e "SELECT DISTINCT index_name FROM information_schema.statistics
      WHERE table_schema=\"labtrace\" AND index_name LIKE \"lt_%\";"'
```

本机实测输出（`*_index_id_table` / `*_index_snapshot_data_table` 是向量索引在
`information_schema.statistics` 里注册的条目，**不是用户表**，`SHOW TABLES` 里看不到）：

```
index_name
lt_chunks_vector_idx
lt_chunks_vector_idx_index_id_table
lt_chunks_vector_idx_index_snapshot_data_table
lt_chunks_ft_idx
lt_experiments_ft_idx
```

`curl http://127.0.0.1:8100/api/health` 应显示 `"mode": "remote"`。

### B.3 手动初始化（不用 init 脚本的场景）

如果 seekdb 服务端已经存在、数据卷也初始化过了（init 脚本只在首次跑），
用 `scripts/init-db.py` 幂等地建库建表建索引：

```bash
python scripts/init-db.py --dry-run \
  --host 127.0.0.1 --port 2881 --user root --password labtrace --database labtrace
# 10 statements, dimension=384, parser=ik

python scripts/init-db.py \
  --host 127.0.0.1 --port 2881 --user root --password labtrace --database labtrace
```

重复执行是安全的，已存在的对象会打印 `exists:`。
也可以覆盖参数：`--dimension 1024`、`--parser ngram`、`--database 别的库名`。

脚本需要 `pymysql`；不在 backend venv 里时会提示
`pymysql is not installed; run this inside the backend virtualenv`。

### B.4 常见问题

**`Bind for 127.0.0.1:2881 failed: port is already allocated`**
本机已有别的东西占用 2881（比如另一个 OceanBase）。设 `SEEKDB_SERVER_PORT=12881`。

**改了 `db/schema.sql` 但容器里没生效**
`INIT_SCRIPTS_PATH` 只在**首次初始化**（数据卷为空）时执行。
要么 `docker compose ... down -v`，要么用 `scripts/init-db.py` 手动补。

**seekdb 容器 OOM / 起不来**
调低 `SEEKDB_MEMORY_LIMIT`、`SEEKDB_DATAFILE_SIZE`、`SEEKDB_LOG_DISK_SIZE`，
并给 Docker Desktop 分配更多内存（本项目验证时 VM 有 8 GB）。

---

## C. 原生开发环境（Linux / macOS / WSL2）

### C.1 安装 uv、Python 3.12、Node

WSL2 Ubuntu 为例：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
uv python install 3.12
# Node 20+：用 nvm 或发行版包管理器
```

### C.2 创建后端虚拟环境

```bash
cd qoder
uv venv --python 3.12 ~/labtrace-venv
uv pip install --python ~/labtrace-venv/bin/python -r backend/requirements.txt
```

> 这个 venv 里没有 pip（uv 创建的），装东西一律用
> `uv pip install --python ~/labtrace-venv/bin/python <pkg>`。

### C.3 安装 PowerContext CLI

```bash
uv tool install --force --with 'pymysql<1.2' 'powercontext[cli,server,seekdb]==1.2.0'
```

**`pymysql<1.2` 是硬约束**：PowerContext 的 seekdb 驱动依赖 aiomysql 0.3.2，
它调用 `pymysql.converters.escape_bytes_prefixed`，而这个函数在 pymysql 1.2 里
被替换成了哨兵字符串，会导致所有 bytes 参数出错。
详见 [TECH_INTEGRATION.md §4.8](TECH_INTEGRATION.md)。

`scripts/dev-up.sh` 与 `scripts/start-powercontext.sh` 在找不到 CLI 时会打印这条安装命令。

### C.4 配置 `.env`

```bash
cp .env.example .env
```

至少要改 `SEEKDB_PATH`，指向一个可写的绝对路径：

```bash
SEEKDB_MODE=embedded
SEEKDB_PATH=/home/<you>/labtrace-data/labtrace-seekdb
SEEKDB_DATABASE=test          # embedded 只有内置的 test 库
EMBEDDING_DIMENSION=384
SEEKDB_FULLTEXT_PARSER=ik
POWERCONTEXT_URL=http://127.0.0.1:8010
LABTRACE_PORT=8100
```

不填 `OPENAI_*` 也可以，只是没有生成式回答（见 README）。

> `.env` 不存在时 `dev-up.sh` 会自动生成一份最小配置，
> PowerContext 的 env 文件也会自动生成到 `~/labtrace-data/powercontext.env`。

### C.5 启动

```bash
bash scripts/dev-up.sh
```

它会：
1. 写 `~/labtrace-data/powercontext.env`（`ACCESS_MODE=disabled`，绑定 `127.0.0.1`）
2. `nohup powercontext server run --env-file ...` 起 PowerContext（端口 `PC_PORT`，默认 8010），
   轮询 `/health/ready` 最多 120 秒
3. `nohup uvicorn app.main:app` 起后端（端口 `API_PORT`，默认 8100），轮询 `/api/health`
4. 打印 `/api/health` 的 JSON

日志：`~/labtrace-data/powercontext.log`、`~/labtrace-data/backend.log`；
PID 文件：`~/labtrace-data/*.pid`。

改端口：

```bash
PC_PORT=8010 API_PORT=8100 bash scripts/dev-up.sh
```

> 后端**没有开 `--reload`**。embedded seekdb 是进程内运行时，
> 热重载会反复重建实例、抢同一个数据目录，导致启动失败或数据目录损坏。
> 改代码后请手动重启：
> ```bash
> bash scripts/dev-down.sh backend && bash scripts/dev-up.sh
> ```

单独启动某个服务：

```bash
bash scripts/start-powercontext.sh   # 前台运行 PowerContext
bash scripts/start-backend.sh        # 前台运行后端
```

### C.6 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。vite 的 `/api` 代理指向
`VITE_API_TARGET`（默认 `http://127.0.0.1:8100`）：

```bash
VITE_API_TARGET=http://127.0.0.1:18100 npm run dev    # 代理到别的后端
```

生产构建：

```bash
npm run build      # 等价于 tsc --noEmit && vite build，产物在 frontend/dist
npm run preview
```

### C.7 停止

```bash
bash scripts/dev-down.sh              # 停后端 + PowerContext
bash scripts/dev-down.sh backend      # 只停后端
bash scripts/dev-down.sh powercontext # 只停 PowerContext
```

`dev-down.sh` 除了读 PID 文件，还会按命令行模式 `pkill`
（用于清理不是 `dev-up.sh` 起的进程），并且**会等进程真正退出**——
否则紧接着的 `dev-up.sh` 可能探活到正在死掉的进程、以为服务还在而跳过启动。

---

## D. 测试与代码检查

### D.1 后端

```bash
cd backend

# 121 个单元测试（不需要任何服务）
PYTHONIOENCODING=utf-8 ~/labtrace-venv/bin/python -m pytest -q

# 再加 27 个 live 测试（需要后端 + seekdb + PowerContext 真的在跑）
LABTRACE_LIVE=1 PYTHONIOENCODING=utf-8 ~/labtrace-venv/bin/python -m pytest -q

# 指向非默认端口的后端
LABTRACE_LIVE=1 LABTRACE_API_URL=http://127.0.0.1:18100 \
  ~/labtrace-venv/bin/python -m pytest -q tests/test_live_api.py
```

- `tests/test_live_api.py` 在 `LABTRACE_LIVE` 未设置时**整体 skip**，
  所以 CI 里没有服务也不会失败
- live 测试会创建临时项目、导入样例文档、跑三种检索、写记忆、恢复上下文，
  最后清理掉自己创建的项目
- `PYTHONIOENCODING=utf-8` 是为了让 pytest 在 Windows/WSL 的控制台正常输出中文

代码检查：

```bash
~/labtrace-venv/bin/ruff check .
~/labtrace-venv/bin/ruff format --check .
# 修复格式：
~/labtrace-venv/bin/ruff format --config backend/pyproject.toml .
```

配置在 `backend/pyproject.toml`：`line-length = 110`、`target-version = "py311"`、
pytest `asyncio_mode = "auto"`。

### D.2 前端

```bash
cd frontend
npm run typecheck    # tsc --noEmit
npm run build        # typecheck + vite build
```

### D.3 端到端演示

```bash
python scripts/e2e_demo.py --api http://127.0.0.1:8100
python scripts/e2e_demo.py --api http://127.0.0.1:8100 --keep
```

需要宿主机有 `httpx`。脚本会创建独立的演示项目，默认结束时删除；
`--keep` 保留项目，方便在 UI 里查看演示结果
（PowerContext Scope 里的记忆无论如何都会保留，以便审计）。

---

## E. 目录与数据落在哪里

| 路径 | 内容 |
| --- | --- |
| `~/labtrace-data/powercontext-seekdb/` | PowerContext 的 embedded seekdb 数据（原生） |
| `~/labtrace-data/labtrace-seekdb/` | LabTrace 的 embedded seekdb 数据（原生，路径由 `SEEKDB_PATH` 决定） |
| `~/labtrace-data/powercontext.env` | 自动生成的 PowerContext 配置 |
| `~/labtrace-data/*.log`、`*.pid` | 日志与 PID |
| Docker 卷 `powercontext-data` | PowerContext 数据（容器） |
| Docker 卷 `labtrace-seekdb-data` | LabTrace embedded seekdb 数据（容器） |
| Docker 卷 `seekdb-server-data` | 独立 seekdb 服务端数据（仅路径 B） |
| `qoder/.env` | 本地环境变量（**不提交**） |

`.gitignore` 排除了 `data/`、`*.log`、`*.pid`、`node_modules/`、`dist/`、
Python 缓存与所有 `.env`（保留 `.example`）。

**彻底重置**：停服务 → 删掉上面这些数据目录 / `docker compose down -v` → 重新启动。
表结构与索引会在启动时自动重建。
