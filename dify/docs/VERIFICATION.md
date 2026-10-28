# 验证记录

## 自动化测试

环境：Python 3.11.9，依赖见 requirements.lock.txt。

~~~text
python -m pytest tests -q
62 passed, 1 warning
~~~

原有规则、传闻、状态、隔离、幂等和异常降级测试全部通过。新增回归覆盖：模型输出包含推理段、最终 JSON 的不同包裹形式、非法意图降级、NPC 最终台词过滤，以及正确解析的撒谎意图实际改变状态并写入记忆。

测试中对记忆服务使用 FakePowerContext/MockTransport 的部分，与下面真实 HTTP 服务验证分开记录。

## 真实 PowerContext 服务

源码固定为官方 cdb8da296a8ed1ad06ac851af7fd05139907a966，本机安装版本元数据 0.1.0。使用真实 PowerContext Server、真实游戏后端和独立测试玩家：

~~~text
python scripts/verify_memory.py --player submission_memory_20261027 --api http://127.0.0.1:8001
全部验证通过：4/4
~~~

实际输出与脱敏审计见 [powercontext-api.txt](evidence/powercontext-api.txt)。覆盖重要事件写入、历史内容召回及成功审计记录。未使用 SQLite 伪造 PowerContext 的记忆查询。

## 真实 Dify 发布页面链路

Dify 1.18.0，DSL 0.7.0；DeepSeek 官方插件 0.0.26，模型 deepseek-flash。入口使用发布应用的普通 WebApp 接口，具体命令：

~~~text
python scripts/verify_dify.py --app-url http://127.0.0.1:8088/chat/你的应用访问码 --player submission_verify_20261027 --output docs/evidence/dify-smoke.json
~~~

实际检查、两次会话 ID、五条输入及最终回答、撒谎后的状态、PowerContext 召回内容和脱敏审计都保存在 [dify-smoke.json](evidence/dify-smoke.json)。本次实测 passed=true，11/11 项检查通过；逐项结果以文件中的 checks 为准。节点执行摘要见 [dify-node-runs.json](evidence/dify-node-runs.json)。

验收关注：

1. 开始游戏与三个 NPC 互动确实经过 Dify。
2. 自然语言撒谎通过模型解析形成真实规则事件，而不是普通聊天。
3. 声望由 50 变为 45，老张信任由 50 变为 40。
4. 新 conversation_id 使用相同 player_id，仍能取回历史记忆。
5. PowerContext remember 和 search/prepare 的真实审计成功。
6. 玩家只看到 NPC 最终台词。

## 联调修复

首次真实模型联调发现两处问题，并在提交 DSL 中修复：

- 供应商将推理段合并进 LLM text，导致原先直接 json.loads 失败。意图校验现在先移除推理段，再解析合法动作。
- 命令解析在自然语言分支也产生默认 chat，聚合器原先优先选择这个上游值。现在优先取已执行的 LLM 分支，命令分支未执行 LLM 时回退到命令结果。

新增 NPC 回复整理节点移除供应商混入的推理段。后端数值规则不受该清理影响。最终图为 18 个节点、21 条边。

## 限制

生成式回答的措辞具有变化；自动化样例使用专用玩家且会重置该玩家。PowerContext 当前采用全文召回，没有配置向量 Embedding。特殊结局的规则与初始化样例另行交付，真实 Dify 样例主要验证核心玩法和记忆链路。
