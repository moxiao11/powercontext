# 来源与技术使用

- 题面：[MiniMax × OceanBase：规有所依](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)，核对于 2026-10-27。
- 参赛基线：[PowerContext competition branch](https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem)，基线 commit `d647275c308e09b7b623f322a26f5c4e85734fb0`；相关资产全部位于 `minimax/`。
- [PowerContext 官方说明](https://github.com/oceanbase/powercontext/blob/master/README_CN.md)及 [Memory 跨会话示例](https://github.com/oceanbase/powercontext/blob/master/examples/jupyter/01_memory_across_sessions.ipynb)。本作品通过固定版本 1.4.1 的官方客户端调用显式 Memory API，未复制或修改其源码。
- [MiniMax 官方文本模型接口示例](https://www.minimaxi.com/models/text)。本作品实现原生 HTTP 适配器；当前未进行真实模型调用。
- [seekdb 官方 Docker 文档](https://github.com/oceanbase/docker-images/blob/main/seekdb/README.md)。Compose 使用官方端口、ROOT_PASSWORD、MEMORY_LIMIT 与数据卷参数。本机实际验证使用已有 WSL seekdb 可执行文件；实际服务版本在验收 JSON 中记录。

Taskboard 业务样例、修改前代码、参考实现、规格、模块与测试均为本作品新编写的自包含资产。参考实现由本地开发生成，绝不标注为 MiniMax 产物。

使用的第三方包遵循各自许可证；本作品的原创代码使用同目录 LICENSE 中的 MIT 许可。
