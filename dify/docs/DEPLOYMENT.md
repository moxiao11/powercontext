# 部署与复现

## 1. 版本及前置条件

已测：Windows、Python 3.11.9、Docker Desktop 4.60.1、Compose 5.0.2、Dify 1.18.0。Docker 本机分配约 8 GiB 内存。需要访问 GitHub、镜像仓库、Dify Marketplace 及模型服务；首次下载镜像可能较慢。

游戏后端版本锁见 requirements.lock.txt；PowerContext 源码固定为 cdb8da296a8ed1ad06ac851af7fd05139907a966。本机安装源码的 2933 个共有跟踪文件与该官方 commit 比较，未发现内容差异。源码匹配用于固定依赖版本，不将本机临时 Git snapshot 当作上游版本。

## 2. PowerContext

安装 uv、Git 和 Python 3.11+ 后：

~~~text
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@cdb8da296a8ed1ad06ac851af7fd05139907a966"
powercontext server run
~~~

默认地址 http://127.0.0.1:8000。检查 GET /health/live。当前不需要 Embedding、Rerank、额外知识库或预置记忆；记忆随测试玩家第一次进入而创建。

PowerContext 的 Windows 支持可能受版本影响，可在 WSL2/Linux 启动服务；此时相应调整游戏后端的 POWERCONTEXT_URL。启用 Server 鉴权时，将令牌放在后端 .env 的 POWERCONTEXT_TOKEN，后端负责附加 Bearer 鉴权头。

来源：https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/

## 3. 游戏后端

在比赛仓库的 dify 目录：

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
~~~

Linux 使用 .venv/bin/python，并以 cp .env.example .env 创建配置。程序从项目根目录加载 .env；SQLite 自动建表，data/ 内包含全部初始规则和状态。

GET http://127.0.0.1:8001/health 应返回 status=ok、powercontext_reachable=true。false 表示长期记忆不可用，不能据此宣称完整功能通过。

主要配置：

| 变量 | 值或作用 |
| --- | --- |
| POWERCONTEXT_URL | 默认 http://127.0.0.1:8000 |
| POWERCONTEXT_TOKEN | 本地默认空；启用鉴权时由运行者配置 |
| DATABASE_URL | 默认 sqlite:///./grudgetown.db |
| GAME_RANDOM_SEED | 42，传闻传播可复现 |
| GAME_MAX_TURNS / GAME_TURNS_PER_DAY | 10 / 2 |

## 4. Dify 1.18.0

已有该版本实例可直接进入下一节。自行部署时先回到比赛仓库根目录（不是 dify 子目录），再获取官方固定版本：

~~~text
git clone --depth 1 --branch 1.18.0 https://github.com/langgenius/dify.git dify-platform
~~~

在 Docker Desktop 中运行以下命令可查看宿主机地址：

~~~text
docker run --rm busybox:latest nslookup host.docker.internal
~~~

取结果中 host.docker.internal 对应的 IPv4。已测本机为 192.168.65.254，这个值需要按自己的 Docker 网络核对。Linux 需要为 api、worker 和 ssrf_proxy 等访问或解析宿主机的服务设置 host.docker.internal:host-gateway 映射，并使用实际网关 IP。

回到本项目 dify 目录调用辅助配置脚本，路径指向仓库根目录下刚下载的官方 docker 目录：

~~~text
python deploy/configure_dify.py --docker-dir ../dify-platform/docker --backend-ip 192.168.65.254
~~~

脚本适用于全新安装：生成独立 .env、随机内部密钥和必需的 Agent Sandbox token，并通过 Compose override 将端口绑定到本机。已有配置时脚本会拒绝覆盖，改为手工合并：

- 网页公开端口 8088，内部 nginx 端口 80。
- EXPOSE_PLUGIN_DEBUGGING_PORT 必须是纯数字 5003；监听地址写在 override 的 ports 中。
- DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN 需要非空随机值。
- SSRF_PROXY_ALLOW_PRIVATE_IPS 填实际宿主机 IPv4/32，保留 SSRF 代理。

进入官方 docker 目录启动：

~~~text
docker compose config --quiet
docker compose up -d
docker compose ps
~~~

init_permissions 成功退出正常；API、数据库、Redis 和沙箱应通过健康检查。初始化页面是 http://localhost:8088/install，由运行者自行创建管理员。镜像齐备后可用 docker compose up -d --pull never 重启。

官方说明：https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose

## 5. 模型、插件与 DSL

本项目使用官方 Marketplace 插件 langgenius/deepseek，已测版本 0.0.26，精确依赖标识已随 DSL 导出。安装来源：https://marketplace.dify.ai/plugins/langgenius/deepseek

在 Dify 配置自己的 DeepSeek 凭据，然后导入 dsl/grudge_town_chatflow.yml。文件为 Dify 1.18.0 实际导出的 DSL 0.7.0，包含供应商依赖、提示词和完整连线，不包含 API Key。

检查 18 个节点、21 条连线，以及四个 LLM 节点：意图解析、老张、阿铁、莉莉丝。已测使用 deepseek-flash；若工作区没有此模型，可手动重新选择自己的可用对话模型，并重新执行验收。意图解析温度为 0。

工作流环境变量 GRUDGE_BACKEND_URL 设置为 http://host.docker.internal:8001。Dify、后端和 PowerContext 的地址由各自运行位置决定，Dify 容器内的 127.0.0.1 指向容器自身。

可从 Dify API 容器检查真实代理链路：

~~~text
docker compose exec -T api python -c "import httpx,os; r=httpx.get('http://host.docker.internal:8001/health',proxy=os.environ['SSRF_PROXY_HTTP_URL'],timeout=10); print(r.status_code,r.text); r.raise_for_status()"
~~~

应返回 HTTP 200，且后端能访问 PowerContext。

## 6. 发布和验证

发布 Chatflow，打开 Dify 生成的 /chat/应用访问码 页面，填写 player_id。按照 docs/DEMO_SCRIPT.md 试玩，或执行：

~~~text
python scripts/verify_dify.py --app-url http://127.0.0.1:8088/chat/你的应用访问码 --player judge_dify --output docs/evidence/dify-smoke.json
~~~

跨会话验证要新建 Dify 会话并保留同一个 player_id。新的 conversation_id 不能作为新的玩家身份。verify_dify.py 会重置指定测试玩家，不要使用要保留进度的玩家 ID。

真实 PowerContext API、scope 创建、remember、search、prepare 的审计由后端持久化；GET /api/memory/log?player_id=对应玩家 返回脱敏记录。提交的证据只包含专用测试玩家。

## 7. 常见故障

| 现象 | 排查 |
| --- | --- |
| 容器长时间 Pulling | 镜像网络下载问题；先确认进度，避免重复下载已完成镜像 |
| API 反复重启 | 查看 docker compose logs api，检查配置类型和必需 token |
| HTTP 节点失败或代理返回 403 | 检查后端地址、宿主机监听、实际宿主机 IP 与 SSRF 允许列表 |
| NPC 对话正常但状态和记忆没有变化 | 使用最新 DSL；检查意图校验和意图聚合节点输出 |
| 记忆写入失败 | 检查 PowerContext 地址、鉴权和后端审计 |
| 模型供应商或模型不存在 | 安装声明的插件，配置凭据并重新绑定四个模型节点 |

运行需要交付的代码与配置均在 dify/；不依赖作者的 .local/、研究目录、数据库文件、PowerContext scope 或 Docker 数据卷。
