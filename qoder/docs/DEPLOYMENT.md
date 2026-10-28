# 部署说明

## 1. 本地 Docker Compose

`docker-compose.yml` 启动三个服务：PowerContext、LabTrace backend、frontend。
后端与 PowerContext 各自持有 seekdb 数据目录；前端 Nginx 代理同源 `/api`。
默认网页 5173、API 8100、PowerContext 8010，只绑定 loopback。

```bash
cd qoder
cp .env.example .env
# 必填 POWERCONTEXT_AUTH_TOKEN 为本地随机值
docker compose up -d --build
docker compose ps
```

Windows 可用 `scripts/start.ps1` 生成配置。独立 seekdb 服务端：

```bash
docker compose -f docker-compose.yml -f docker/docker-compose.seekdb-server.yml up -d --build
```

该模式增加官方 seekdb 容器，后端改用 remote；PowerContext 继续用自己的 embedded 存储。
`db/schema.sql` 首次初始化建表。已有数据卷不会再次执行初始化文件。
嵌入式 seekdb 需要 POSIX，Windows 通过 Docker / WSL 运行。

持久化卷：`powercontext-data`、`labtrace-seekdb-data`，独立模式另有 `seekdb-server-data`。
停止用 `docker compose down`；不要添加 `-v`，除非明确要删除数据。

## 2. 端口和配置

`LABTRACE_WEB_PORT` / `LABTRACE_API_PORT` / `POWERCONTEXT_PORT` / `SEEKDB_SERVER_PORT` 可更改宿主端口。
本机运行值为 15173 / 18100 / 18010 / 12881；干净环境默认值不同。

PowerContext 容器绑定非 loopback，因此启用 `ACCESS_MODE=enforced`；随机 token 同时交给后端。
模型配置可选。PowerContext 推理标识必须完全 unset，不能设置为空字符串，见示例文件。

Nginx 使用 Docker DNS 动态解析 backend；重建后端容器不会继续使用旧 IP。
前端生产镜像以锁文件执行 `npm ci`。

## 3. 健康与验收

```bash
curl http://127.0.0.1:5173/api/health
python scripts/e2e_demo.py --api http://127.0.0.1:5173 --keep
```

前端同源健康应显示 seekdb.connected 和 powercontext.ready。
从网页入口验收能覆盖代理链路，避免只检查后端端口而忽略网页 502。
完整测试和实际输出见 `VERIFICATION.md`。

如需验证物理重启后的持久化，可在本地空闲时运行：

```bash
python scripts/verify_persistence.py --api http://127.0.0.1:5173 --container labtrace-powercontext
```

该命令会短暂重启明确指定的容器、创建和清理测试项目，以全新客户端核对条目 ID 和 Handoff 版本。

## 4. 对外运行

当前无多用户鉴权。正式对外提供在线工作台前需部署独立 Linux 服务、访问控制、TLS 和备份。
公开展示站只承载项目介绍与原创示例，不连接本机私人科研数据。
各项密钥只存服务端环境变量，不进入前端、ZIP 或 Git。

## 5. Qoder Sites 展示站

当前尚未真实发布，尚未获得可用于本次操作的 Qoder 站点会话及站点信息。

Qoder Sites 支持静态网站，也提供含数据库、服务函数与存储的 Agent App；不同套餐能力有差异。
这不等于其托管环境能原生运行本项目的 Python / Docker / seekdb 进程。
本项目采用独立科研后端 + Sites 展示入口的交付方式。

官方参考：[Sites](https://docs.qoder.com/qoder/sites)、[CLI Sites](https://docs.qoder.com/cli/sites)。

### 构建

```bash
cd qoder
python scripts/build_site.py
# 可用 --repository-url 指定真实比赛仓库；也可从 submission.local.json 读取
python -m http.server 8899 --directory dist/site
```

发布目录为 `dist/site/`，含 index.html、样式、文档、实际截图、验证日志和原创样例。
缺少仓库地址时显示明确待填状态；不会误链 oceanbase 上游作为自己的提交仓库。

### 在 Qoder 中发布

1. 使用个人 Qoder 账号，在新任务中引用 `dist/site/`，请求 Sites 根据该目录创建项目展示站产物。
2. 核对网站预览：项目简介、功能、截图、代码仓库、文档和验证入口。
3. 在 Sites 面板点击“发布”，等待成功并复制真实站点地址。
4. 在分享中选择“任何人可访问”，确认公开访问。Teams / Enterprise 无公开访问选项。
5. 无痕窗口打开，核对截图、文档链接与代码仓库；保存验证记录。
6. 把 URL、Qoder UID、真实开发截图路径填到 `submission.local.json`。

若当前 Qoder 界面无法直接导入目录，可在对话中提供源文件和资源，请 Sites 创建网站产物后发布。
不假定界面一定提供“上传文件夹”按钮。也不能以其他厂商 Sites 的网址代替 Qoder Sites。
发布后修改需要再次发布，评审结束前保持站点在线。

## 6. 提交检查

```bash
python scripts/submission.py check --strict
```

所有条件应为 pass；任何 pending 都需真实补齐。工具不替代 Qoder 主要开发证明或站点归属核实。
细节见 `SUBMISSION.md`。
