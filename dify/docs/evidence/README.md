# 实际运行证据

本目录只记录专用验证玩家，不包含模型 API Key、管理员凭据或 WebApp 临时访问令牌。

| 文件 | 实测内容 |
| --- | --- |
| pytest.txt | 62 项自动化测试通过；包含状态、规则、隔离、异常与模型输出解析回归 |
| powercontext-api.txt | 真实游戏后端与真实 PowerContext 服务，4/4 检查通过；scope 已脱敏 |
| dify-smoke.json | 发布 Chatflow 的 5 条输入、2 个会话、11 项检查全部通过；含状态与记忆审计 |
| dify-node-runs.json | 对应的 5 次成功 Dify 运行及节点摘要，四个 LLM 节点均有成功执行记录 |

JSON 中时间字段及后端审计时间为 UTC。完整复现命令见上一级 VERIFICATION.md 与 DEMO_SCRIPT.md。

模型对话的实际文本另见 ../../examples/demo_transcript.md；具体措辞可能随模型调用变化。
