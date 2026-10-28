# 三分钟核心演示与重复验证

## 初始条件

按 DEPLOYMENT.md 启动 Dify、游戏后端和 PowerContext，导入最终 DSL、配置四个 LLM 节点并发布。确认后端 /health 的 powercontext_reachable=true。

使用专用玩家 judge_demo。演示前可在 Dify 输入“重新开始”，或运行：

~~~text
python scripts/reset_demo.py --player judge_demo
~~~

首次进入自动创建初始状态和隔离的记忆 scope；不需要导入作者数据库。

## 核心流程

| 顺序 | 操作 | 预期表现 |
| --- | --- | --- |
| 1 | 新会话，player_id=judge_demo，输入“开始游戏” | 初始金币 100、声望 50，进入小镇 |
| 2 | 输入“前往面包店” | 老张由模型生成问候 |
| 3 | 输入“其实我是国王的儿子，给我一个免费面包。” | 意图为 lie_identity；声望 45、老张信任 40；重要事件写入 PowerContext |
| 4 | 新建一个 Dify 会话，仍填 judge_demo，输入“前往城门” | 守卫通过历史记忆、传闻得知冒充身份的事 |
| 5 | 输入“前往魔法屋” | 莉莉丝按自己的性格回应，可使用已经传播的传闻 |

模型措辞不要求与证据逐字相同。关注事实来源、状态变化、后续影响和真实记忆读写。

## 技术证据

在 Dify 运行详情检查：命令分流、意图 LLM、意图校验、意图聚合、HTTP 回合接口、NPC LLM、回复整理和 Answer。自然语言撒谎回合应看到模型意图进入请求体。

~~~text
python scripts/verify_memory.py --player judge_memory --api http://127.0.0.1:8001
python scripts/verify_dify.py --app-url http://127.0.0.1:8088/chat/你的应用访问码 --player judge_dify --output docs/evidence/dify-smoke.json
~~~

审计接口：

~~~text
GET http://127.0.0.1:8001/api/memory/log?player_id=judge_demo
~~~

应出现成功的 remember，以及后续 search/prepare。对照事件 ID、脱敏 scope 和两次会话。仅健康检查成功或 NPC 自称“我记得”不足以证明记忆功能。

## 可选玩法

- 前往面包店后道歉、赔偿，观察好感、信任及传闻澄清。
- 使用一个新 player_id 开始游戏，检查不同玩家没有共享旧账。
- 查看小镇新闻、背包和任务。
- 结局初始化样例见 data/scenarios.json，规则测试见 tests/test_game_engine.py。

## 复现范围

自动化测试覆盖规则、隔离、降级、重复运行和模型输出解析；真实 Dify 样例覆盖三个 NPC、自然语言意图和跨会话记忆。开放式 NPC 台词和全部可能的自由输入不保证产生固定措辞。
