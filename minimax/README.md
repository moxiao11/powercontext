# 规有所依：SDD 工程上下文模块

本作品为开发助手提供当前有效的规格、相关实现和测试，通过 seekdb 存储与查询工程资料，通过 PowerContext 保存并复用任务状态，再由 MiniMax 参与局部代码修改。

**当前交付状态：本地参考模式已验证。尚无 MiniMax 凭据，真实模型参与项未完成，不能按题面宣称获得 20 分。** 参见 `SUBMISSION_STATUS.md` 和 `evidence/reference-final/acceptance.json`。参考模式会明确输出 `all_six_passed=false`，不会伪造 MiniMax 记录。

## 依赖和目录

- Python 3.11+；本次实际验证使用 Windows Python 3.13.9、WSL Ubuntu 22.04 的 seekdb 服务。
- `powercontext[cli,server]==1.4.1`、`PyMySQL==1.2.0`、`httpx==0.28.1`、`pytest==8.4.2`。
- seekdb 或 OceanBase 的 MySQL 协议服务。需要创建专用数据库的权限；不要求修改数据库源码。
- 真实开发模式需要 MiniMax API 凭据及与该账号兼容的模型、端点。

| 目录 | 用途 |
| --- | --- |
| `sdd_context/` | 导入、检索、上下文、持久状态、MiniMax 助手与 CLI |
| `examples/taskboard/project/` | 修改前业务工程、当前和历史规格、固定测试和初始数据 |
| `examples/taskboard/reference/` | 本地编写的功能参考实现，明确不属于 MiniMax 产物 |
| `tests/` | 模块单元测试和真实服务集成测试 |
| `scripts/` | PowerContext 启动、服务检查、测试记录、提交证据检查 |
| `evidence/` | 已执行验证的快照、差异、日志、版本和来源 |
| `runtime/` | 忽略提交的数据库、临时目录、新运行和审计文件 |

所有命令在本文件所在的 `minimax/` 目录执行。业务样例为本作品自包含的 Python 服务，不依赖其他目录下的 seekdb 源码或本机私有文件。

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

后续示例的 `python` 指上述虚拟环境的 Python；Windows 可以使用完整命令 `.\.venv\Scripts\python.exe`，Linux 使用 `.venv/bin/python`。无需激活虚拟环境也能运行。

## 准备数据库与 PowerContext

在 `.env` 中配置 `SDD_DB_HOST/PORT/USER/PASSWORD/NAME`。默认连接本机 `12890`，专用数据库名为 `sdd_context`。可直接连接已有 seekdb/OceanBase 实例。

没有现成数据库时，可使用附带的官方镜像 Compose 配置：

```bash
docker compose up -d seekdb
```

此路径需要用户已安装 Docker。当前机器未安装 Docker，因此本次实际验证使用独立 WSL seekdb 进程；Compose 路径未在本机执行验证。默认镜像遵循官方快速启动的 `oceanbase/seekdb:latest`，正式复现建议将 `SEEKDB_IMAGE` 设为选定镜像的 digest。Compose 使用具名卷，兼容官方新旧版本的数据目录；不会挂载个人目录。

在独立终端启动真实 PowerContext：

```bash
python scripts/powercontext_server.py
```

该脚本调用已安装的 PowerContext 官方 CLI，仅绑定 `127.0.0.1:18080`，数据保存于 `runtime/powercontext/`，无需为显式状态保存配置模型。默认访问模式仅用于本机验证。停止后再次执行同一命令，会重新打开原数据库。

在另一终端检查服务并初始化工程资料表：

```bash
python scripts/wait_services.py --timeout 180
python -m sdd_context init
```

PowerContext 自身的 SQLite 用于任务状态；工程资料与索引始终存储于 seekdb/OceanBase，检索结果直接进入开发上下文，没有本地 JSON 或 SQLite 检索替代路径。

## 运行自包含验证

```bash
python -m sdd_context demo --mode reference
```

每次运行创建新的运行目录和项目 ID，从空任务状态开始，不删除已有数据。输出给出运行目录。流程包含：历史规格导入、当前规格替换、上下文来源检查、修改前测试、参考代码修改、修改后测试、PowerContext 保存、新进程恢复、规格更新、旧测试结果失效判断及重新验证。

预期修改前目标测试为 **8 failed、1 passed**，失败来自未实现的筛选和参数校验；修改后为 **9 passed**，回归测试为 **10 passed**。目标测试、回归测试和夹具在前后保持相同哈希。

参考模式退出 0 仅表示实现验证完成，`acceptance.json` 中 MiniMax 项仍为 `blocked_no_credentials`，`submission_ready=false`。

## 真实 MiniMax 开发流程

在本机 `.env` 中填写凭据，或通过进程环境设置 `MINIMAX_API_KEY`。不要将密钥提交到 Git 或发送到聊天。按凭据类型设置 `MINIMAX_API_URL`、`MINIMAX_MODEL`；默认采用 MiniMax 官方原生文本接口与 `MiniMax-M2.5`。

```bash
python -m sdd_context demo --mode live
```

该命令从修改前快照开始，把数据库检索出的规格、实现、测试和恢复状态发送给 MiniMax。模型只能返回已索引实现文件的完整 Python 源码，测试与配置不属于可编辑范围。失败时最多提供三轮测试反馈；不保证模型每次产生相同补丁。

请求记录不含 Authorization，响应记录只保存最终可见代码、摘要、模型、响应 ID、用量和时间，不保存私有思维链。缺少凭据时退出 2 并生成 `blocked.json`，不会自动转为参考模式。

将命令输出的运行目录传入提交检查器：

```bash
python scripts/verify_submission.py <运行目录>
```

只有真实模式的六项状态全部通过且相关记录齐全，检查器才退出 0。对交付的参考记录执行此命令，预期退出 1，并指出 MiniMax 记录缺失。

## 独立调用入口

```bash
python -m sdd_context import --project examples/taskboard/project
python -m sdd_context context --project examples/taskboard/project --task "taskboard status filter" --output runtime/context.json
```

输入是工程目录和自然语言任务；工程 `project.json` 声明规格文件、代码/测试来源、标签及显式关系。规格支持 `active/superseded/retired`，重新导入时缺失项也会退出当前检索。导入事务按项目加锁，保留历史版本，相同内容重复导入不新增版本。

输出为 `sdd.context.v1` JSON，包含 `specs/code/tests/progress`；每条资料带真实相对路径、符号、行号、索引版本、内容及文件哈希。来源已修改但未重新导入时，模块拒绝继续输出旧内容。

保存状态时，先创建一个用户自定义 JSON 文件，例如：

```json
{"completed":["baseline-tests"],"pending":["implement","verify"],"checks_passed":false}
```

```bash
python -m sdd_context save-state --project examples/taskboard/project --task-id my-task --pointer runtime/my-task-pointer.json --state <状态文件>
python -m sdd_context resume --project examples/taskboard/project --task "taskboard status filter" --pointer runtime/my-task-pointer.json
```

本地 pointer 仅保存 PowerContext 的 scope 和精确 artifact 地址；任务内容由新客户端从 PowerContext 获取。已保存的 `pending` 会决定 `next_action`；规格、代码或测试哈希变化时，验证状态变成 `stale`，下一步变成 `revalidate`。

## 模块测试与重置

```bash
python scripts/check.py --integration --output runtime/checks-1
```

此命令运行模块单元测试和连接真实服务的集成测试，记录命令、退出码、源码哈希、日志和 JUnit。只运行无服务测试可去掉 `--integration`。业务测试由 `demo` 在独立工程目录中执行。

重置演示只需再次运行 `demo`，它会创建新的项目、Scope 和工作副本；指定 `--output` 时必须选择新目录。评审不需要复用已交付日志里的本机绝对路径或 PowerContext artifact。日志中的路径仅是当次运行记录，新运行会生成当前机器的路径和新引用。

停止 PowerContext 使用运行终端的 Ctrl+C；Docker 数据库使用 `docker compose stop seekdb`。不要把删除数据库当作重置步骤。

## 已知限制

- 当前无真实 MiniMax 凭据及参赛私有仓库，尚未完成模型调用和平台固定提交。
- 检索使用标签、关键词和显式关系，不提供大型仓库的向量召回、复杂规格冲突自动裁决或完整 Agent 会话恢复。
- 规格生命周期由工程资料明确声明；多个相互矛盾的活跃规格需要维护者修订。
- 哈希包含整个已声明工程快照；无关资料变化也可能保守地要求重新验证。
- CLI、样例和记录面向单用户本地验收；没有多用户权限与生产服务部署承诺。

技术分工见 `ARCHITECTURE.md`，验证步骤见 `VALIDATION.md`，第三方资料来源见 `SOURCES.md`。
