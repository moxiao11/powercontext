# 提交清单

## 仓库与分支

平台绑定仓库为 https://github.com/moxiao11/powercontext，分支为 2026-competition-ecosystem。此次工作从该远程分支的 a925e7ac4e0bb12e056e08d28f578c6718e66eb6 开始，新增资产均在 dify/，保留其他赛题目录。

上述分支基础与 PowerContext 运行依赖是两回事：运行依赖固定于 SOURCES.md 所列官方源码 commit。

## 交付内容

- dsl/grudge_town_chatflow.yml：从实际 Dify 配置导出，并包含联调修复的最终 Chatflow。
- README.md、docs/DEPLOYMENT.md：玩法、组件分工、软件和插件版本、完整启动及网络设置。
- backend/、data/、prompts/：规则源码、全部初始数据、NPC 人格提示词。
- deploy/configure_dify.py：全新官方 Dify 安装的本机配置辅助工具。
- scripts/：玩家初始化、重置、真实记忆验证及已发布 Dify 链路验证。
- tests/、requirements.lock.txt：自动化测试与已测依赖版本。
- docs/evidence/：真实运行的 JSON、脱敏日志和节点摘要。
- docs/SOURCES.md：上游来源、固定版本和插件来源。

正式入口为 Dify 发布的应用页面。作者机器上的 localhost 地址用于本机演示，评审需按说明重新部署，使用自己的模型服务凭据。

## 提交前检查

~~~text
git status --short
git diff --cached --stat
git diff --cached --check
~~~

不要加入真实 .env、API Key、访问令牌、数据库、虚拟环境、Docker 数据卷、镜像缓存或作者本机的研究目录。DSL 的 Secret 环境变量导出保持关闭。

推送后取得完整 commit：

~~~text
git push origin 2026-competition-ecosystem
git rev-parse HEAD
~~~

在测评平台选择 Dify 题目，按表单要求选择绑定的仓库、分支或填写完整 commit hash，然后提交评测。若平台还要求作品说明或附件，可使用 README、DEMO_SCRIPT 和 evidence/ 中的材料。页面字段以平台当前显示为准。

仓库可见性和导入方式应符合赛事正式要求，以平台绑定地址和赛事说明核对；本次整理不更改仓库的可见性。
