# 验证说明与真实记录

本轮验证日期：2026-10-28（Asia/Shanghai）。环境：Windows + WSL2 Ubuntu 22.04 + Docker Desktop。
后端、seekdb、PowerContext 和前端都为真实运行的服务。

## 本轮结果

| 验证 | 结果 | 原始证据 |
| --- | --- | --- |
| 单元 + 真实服务测试 | **148 passed in 18.70s**，无 skipped / xfail | `evidence/pytest-live-2026-10-28.txt` |
| 干净 Docker 镜像复测 | **148 passed in 27.56s**，新构建镜像通过前端入口访问服务 | `evidence/pytest-container-2026-10-28.txt` |
| 演示 A–D | 全部检查通过，exit 0 | `evidence/e2e-demo-2026-10-28.txt` |
| seekdb | `5.7.25-OceanBase seekdb-v1.4.0.0`，remote 模式 | 演示日志 `/api/health` |
| PowerContext | Server 1.2.0，Memory + committed Handoff 可读取 | 演示日志及 live 测试 |
| 前端 | TypeScript 检查与 Vite 构建通过 | `npm run build` |
| PDF | 原创两页文档真实上传 / 检索，第 2 页引用准确，项目隔离通过 | `test_submission_live.py` |
| 跨会话纠正 | 独立 HTTP 客户端读取修订记忆，拒绝陈旧覆盖，旧快照不作为当前计划 | 同上 |
| 服务重启持久化 | 重启 PowerContext 容器后用全新 HTTP 客户端读取；条目 ID 和 Handoff 版本一致 | `evidence/persistence-restart-2026-10-28.json` |
| 浏览器 | 网页能读到 3 篇资料、4 组实验、8 条有效记忆；移动布局可查看 | `evidence/overview-2026-10-28.png` |

测试构成：**121 个单元测试 + 27 个真实服务集成测试**。
单元测试使用测试替身隔离逻辑，不能作为实际数据库运行证明。
27 个 live 测试直接调用网页同源 `/api`，真实经过 Nginx、FastAPI、seekdb 和 PowerContext。

本轮演示项目：`prj_132c46262c604e98`；Scope：`scp_50a0fhq99v2mdp9t9qtcfpbkja`。
ID 是本地本次运行值，重跑会创建新 ID，不应硬编码到程序。
所有实验数字都是原创示例数据，不能作为真实科研成果或真实用户提效数据。

## 独立复现

按 `SETUP.md` 启动服务。默认 API 为 8100；本机使用 18100，网页为 15173。

```bash
cd qoder
python scripts/e2e_demo.py --api http://127.0.0.1:8100 --keep
cd backend
pip install -r requirements.txt
python -m pytest -q
# 预期 121 passed，27 skipped：live 默认关闭
LABTRACE_LIVE=1 LABTRACE_API_URL=http://127.0.0.1:5173 python -m pytest -q
# 预期 148 passed；5173 为前端同源入口，含代理链路验证
cd ../frontend
npm ci
npm run build
```

Windows PowerShell 的 live 环境变量：

```powershell
$env:LABTRACE_LIVE='1'
$env:LABTRACE_API_URL='http://127.0.0.1:5173'
python -m pytest -q
```

## 手动验收 A–D

1. **A / 论文**：创建项目，上传 `sample-data/papers/` 的 Markdown；三种检索模式分别输入“场景记忆”。返回实际 seekdb 引擎、SQL 模式、引用和分块原文。再上传原创 PDF，关键词输入 `ROOMMERGE2026`，预期引用均为第 2 页。
2. **B / 实验**：在实验中心导入 `sample-data/experiments/sample-experiments.json`；对比 baseline 与 HSM v1，accuracy 从 41.2 到 58.7，差值 17.5；查看 abandoned 记录的失败原因。
3. **C / 记忆**：在科研助手保存研究进度，填写明确的决策、原因及下一步；确认 Memory / Source / Handoff 返回真实引用。清空会话或重新开浏览器，再点“继续上次研究”。在 Memory 页修订计划后再次恢复，当前摘要应显示修订内容，Handoff 只作为历史快照。
4. **D / 周报**：选择记录所在日期，生成周报、预览、编辑、复制和下载 Markdown。指标与实验记录逐项核对。

## 发布与运行恢复验证

- Qoder Sites 已发布：https://labtrace-research-186qw7bzjxs.qoder.zone/ ，范围为“任何人都可访问”。
- 12 项不带 Cookie / Authorization 的 HTTP 检查通过；CSS 首次连接超时后重试通过，原始记录保留两次结果，见 `evidence/site-anonymous-2026-10-28.json`。
- Windows Docker Desktop socket 故障恢复后，四个容器 healthy，seekdb / PowerContext 可用，原项目保留 3 篇资料、4 条实验和 8 条记忆，见 `evidence/docker-recovery-2026-10-28.json`。
- Qoder 原对话截图、账号 ID 和发布界面已归档，见 `QODER_DEVELOPMENT_LOG.md`。

## 未完成或未验证

- 未配置真实模型 / Embedding API；生成式回答和语义检索质量未验证。当前明确标注哈希向量与证据摘录。
- 未验证 PowerContext 的自动抽取 / Topic Memory / Profile。显式 Memory 与 Handoff 不依赖这些能力。
- 报名仓库为 `https://github.com/moxiao11/powercontext`，使用本地 `competition` 远端；GitHub 写入检查返回 403，用户选择稍后授权，代码仍未推送。
- 知识关联图未实现；不影响核心 A–D。
- 无生产级多用户鉴权、并发压测、真实用户效果数据；当前为本地单用户工作台。

不得将未完成项标为通过。提交前使用 `SUBMISSION.md` 的严格检查。
