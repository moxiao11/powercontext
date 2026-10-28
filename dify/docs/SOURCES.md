# 来源与依赖版本

## 比赛基础分支

- 平台绑定仓库：https://github.com/moxiao11/powercontext
- 分支：2026-competition-ecosystem
- 此次开发基线：a925e7ac4e0bb12e056e08d28f578c6718e66eb6
- 所有作品文件位于 dify/。

## Dify

- 官方仓库：https://github.com/langgenius/dify
- 已测版本：1.18.0，发布提交 50abea97062110044f15d0e03ccecadd9ccc87ca。
- 部署参考：https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose
- DSL 导入导出：https://docs.dify.ai/en/cloud/use-dify/workspace/app-management

DSL 从本作品实际配置导出。模型、提示词和图结构随文件交付；供应商密钥由运行者配置。所依赖的软件许可证按各上游 LICENSE 执行。

## DeepSeek 插件和模型

- 名称：langgenius/deepseek。
- 官方 Marketplace：https://marketplace.dify.ai/plugins/langgenius/deepseek
- 已测插件版本：0.0.26。
- 精确标识：langgenius/deepseek:0.0.26@bdf47cb41e9062bba00d26625d2a795c1874011d8ce64bff738c44b5a31787ea。
- 已测模型名：deepseek-flash。四个 LLM 节点均使用此模型；意图解析温度为 0。
- 插件作为现成依赖安装，不打包作者账号凭据。

## PowerContext

- 官方仓库：https://github.com/oceanbase/powercontext
- 已测源码固定为 cdb8da296a8ed1ad06ac851af7fd05139907a966。
- 本机安装元数据版本：0.1.0。
- 已将本机安装来源的 2933 个共有跟踪文件内容，与该官方 commit 的 Git blob 摘要比较，全部一致。
- API 参考：https://powercontext.oceanbase.io/zh/docs/develop/api-quickstart/
- 接入：游戏后端通过 HTTP 调用 /v1/scopes、/v1/memory/remember、/v1/memory/search、/v1/context/prepare。
- 当前使用全文检索模式，原始状态、规则和传闻来源保存在游戏 SQLite 中。

## 本作品代码和数据

游戏规则、NPC 设定、状态机、传闻引擎、记忆适配器、提示词、验证脚本和数据配置为本作品实现。未直接复用题面列出的娱乐工作流。NPC 实际示例由已配置模型在本作品运行时生成，输出形式和措辞允许变化。
