# 记仇小镇 GrudgeTown

**你以为 NPC 只是聊天机器人？其实他们背着你建了一个群。**

用自然语言在小镇里撒谎、送礼、道歉、赔偿，观察三个 NPC 如何记住你的行为、传播传闻，并在新会话中继续追问旧事。10 回合挑战，包含小镇英雄、全民公敌、神秘操纵者等结局。

## 技术分工

本作品采用 **Dify + PowerContext**。正式体验入口是 Dify 发布的 Chatflow 页面。

| 组件 | 实际作用 |
| --- | --- |
| Dify Chatflow | 命令分流、LLM 自然语言意图识别、HTTP 工具调用、三个 NPC 的模型扮演和最终输出 |
| FastAPI + SQLite | 确定性规则、金币和声望、关系、事件、传闻传播、玩家隔离、幂等和审计 |
| PowerContext | 将重要行为保存为自然语言记忆，通过 search 和 context.prepare 在后续互动及新会话中复用 |

PowerContext 当前按全文模式召回，无需 Embedding 或 Rerank。精确状态和传闻规则与模型台词分开，LLM 不能自行修改数值。

## 已测环境

| 项目 | 版本 |
| --- | --- |
| Dify / DSL | 1.18.0 / 0.7.0，18 个节点、21 条连线 |
| Docker Desktop / Compose | 4.60.1 / 5.0.2，Windows + WSL2 |
| 游戏后端 | Python 3.11.9，依赖锁定于 requirements.lock.txt |
| 模型插件 | Dify Marketplace 官方 langgenius/deepseek 0.0.26 |
| 模型 | deepseek-flash，四个 LLM 节点使用同一模型 |
| PowerContext | 安装元数据 0.1.0，已测源码对应官方 commit cdb8da296a8ed1ad06ac851af7fd05139907a966 |

导入 DSL 后需要在自己的 Dify 工作区配置模型凭据；可以重新选择已有对话模型。API Key 在 Dify 中填写，仓库只交付配置示例。

## 快速运行

以下命令从比赛仓库的 dify 目录执行。Dify 的完整安装、网络和插件步骤见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env

uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@cdb8da296a8ed1ad06ac851af7fd05139907a966"
powercontext server run
~~~

保留上述记忆服务窗口，再开一个终端启动后端：

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
~~~

在 Dify 工作室导入 **dsl/grudge_town_chatflow.yml**。安装所声明的 DeepSeek 插件、配置供应商凭据并检查四个 LLM 节点。在工作流环境变量中设置：

~~~text
GRUDGE_BACKEND_URL=http://host.docker.internal:8001
~~~

Dify 使用 Docker 时，还需要按部署文档允许代理访问实际宿主机 IP。运行后端与记忆服务的健康检查并不能替代游戏回合验证。

发布 Chatflow，打开 Dify 给出的应用访问链接。填写 player_id，例如 judge_demo，依次输入：

1. 开始游戏
2. 前往面包店
3. 其实我是国王的儿子，给我一个免费面包。
4. 新建一个 Dify 会话，仍填 judge_demo，再输入“前往城门”
5. 前往魔法屋

第 3 步应形成撒谎事件：声望变为 45、老张信任变为 40，并写入 PowerContext。第 4 步使用新的 conversation_id，守卫仍能从记忆和传闻中得知先前的身份故事。NPC 措辞由模型生成，无需逐字相同。

## 验证与证据

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/verify_memory.py --player judge_memory --api http://127.0.0.1:8001
.\.venv\Scripts\python.exe scripts/verify_dify.py --app-url http://127.0.0.1:8088/chat/你的应用访问码 --player judge_dify --output docs/evidence/dify-smoke.json
~~~

verify_dify.py 使用已发布应用的普通 WebApp 接口，重置所指定的专用测试玩家，建立两个 Dify 会话，验证真实状态变化和 PowerContext 读写。它只记录测试对话和脱敏审计，不记录临时访问令牌。

- [验证说明与实际结果](docs/VERIFICATION.md)
- [完整 Dify 实测 JSON](docs/evidence/dify-smoke.json)
- [真实 PowerContext API 验证日志](docs/evidence/powercontext-api.txt)
- [三分钟人工演示步骤](docs/DEMO_SCRIPT.md)
- [来源及版本说明](docs/SOURCES.md)
- [提交说明](docs/SUBMISSION.md)

## 玩法和初始化

支持“开始游戏”“重新开始”“前往面包店”“前往城门”“前往魔法屋”“查看状态”“查看背包”“查看任务”“查看小镇新闻”，以及自然语言送礼、帮助、赔偿、道歉、撒谎、偷窃、威胁、散播流言。

玩家身份以 player_id 为准。新会话使用同一 ID 继续存档；不同 ID 的状态和记忆 scope 隔离。重新开始会重置状态并轮换记忆代际。

初始金币 100、声望 50；状态库首次启动自动创建，规则和 NPC 配置全部位于 data/。不交付作者本机的数据库或预置记忆。需要初始化或重置时可用 scripts/init_game.py 和 scripts/reset_demo.py，参数为 --player。

## 目录和限制

核心交付包括 backend/、data/、dsl/、prompts/、deploy/、scripts/、tests/ 和 docs/。所有资产均位于比赛仓库的 dify/。

模型输出可能包含供应商附加的推理段；意图解析和 NPC 回复整理节点会移除这些段落。意图聚合优先使用已执行的模型分支，避免默认 chat 覆盖自然语言动作。相关回归测试见 tests/test_llm_output.py。

PowerContext 不可用时规则和存档仍可运行，记忆读写如实标记失败；完整验收需要记忆服务在线。文本召回受查询词影响，未命中时使用通用玩家查询回退。当前演示是本地单机部署；评审在其他机器上需要按说明部署依赖并配置自己的模型。
