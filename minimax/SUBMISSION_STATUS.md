# 当前提交状态

记录日期：2026-10-28。

源码基于题目指定的 `2026-competition-ecosystem` 分支。真实 MiniMax 代码修改及六项本地验收全部完成，提交证据检查器返回 `submission_evidence_ready=true`。参赛仓库为 `https://github.com/moxiao11/powercontext`，远端推送及平台提交尚待完成；本地结果不替代评审最终结果。

仓库目前为公开 fork，已向用户说明；用户明确选择继续提交到该仓库。保留其现有可见性及 Dify、Qoder 等其他赛道内容，不强制覆盖已有分支。

## 真实 MiniMax 开发记录

- 调用接口：`https://api.minimax.cn/v1/chat/completions`，请求与返回模型均为 `MiniMax-M2.5`。
- 响应 ID：`0730f71cdffe3353482a38ec7b5e29ff`。
- 首次调用用量：输入 2568 token、输出 362 token，共 2930 token；只记录思考 token 计数，未保存思维链。
- 模型调用耗时：7.637 秒。
- 输入为 seekdb 实际检索的当前规格、实现、固定测试及 PowerContext 恢复的任务状态。
- 首次生成实现状态校验、先筛选再排序分页，并保留原有行为；返回代码与最终源码快照一致。

完整请求和可见返回在 `evidence/live-final/minimax-attempt-1/`，差异为 `evidence/live-final/change.diff`。所有记录不含 API 密钥。

## 本机已执行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 模块单元测试 | 20 项通过 | `evidence/checks-live-final/results.log` |
| 真实 seekdb／PowerContext 集成测试 | 5 项通过 | 同上及 `results.xml` |
| 修改前目标测试 | 8 failed、1 passed，环境错误 0 | `evidence/live-final/target-before.*` |
| 修改后目标测试 | 9 passed | `evidence/live-final/target-after-1.*` |
| 修改前后回归测试 | 各 10 passed | `evidence/live-final/regression-*.json` |
| MiniMax 实际参与 | 首次真实生成即通过测试 | `evidence/live-final/minimax-attempt-1/` |
| 规格替换、失效项排除、来源定位 | 已验证 | `context-v1.json`、`context-v2.json`、`source-expectations.json` |
| seekdb 工程资料入库及实际查询 | 已验证 | `database.jsonl`、`database-history.json` |
| 空状态保存与新操作系统进程恢复 | 已验证 | `powercontext.jsonl`、`resume-*-process.json` |
| 规格变化使原验证失效，再验证后恢复 | 已验证 | `resume-spec-updated.json`、`resume-final.json` |
| 源码包解压后在独立目录运行完整演示 | 退出 0 | `evidence/clean-source-check.json` |
| 缺少密钥和参考模式不能通过提交检查 | 均按预期阻断 | `evidence/release-checks.json` |

本次实际业务修改由 MiniMax 生成。完整结果由 `evidence/live-final/acceptance.json` 记录，六项均为 passed，`all_six_passed=true`、`submission_ready=true`，表示本地作品证据完整。历史参考模式记录保留于 `evidence/reference-final/`，其 `all_six_passed=false` 不作为真实模型参与证据。表中未带前缀的业务证据路径均相对 `evidence/live-final/`。

服务曾在中断后停止，一次复测因连接拒绝而失败，记录保留于 `evidence/checks-final-service-unavailable/`；当时尚未执行业务前后对比。恢复服务后重新执行最终验证，环境故障未计作功能失败。

打包审计还发现 Windows 文本写入会转换代码快照的换行。最终实现已改为按原始字节复制前后快照，并在演示中强制核对快照哈希与测试源码哈希；Git 规则保留运行证据的原始字节。修复前记录保留于带 `before-byte-snapshot-fix` 后缀的证据目录。

## 尚待完成的远端步骤

1. 将基于指定比赛分支、包含源码与真实验收证据的最终提交推送到 `moxiao11/powercontext`。
2. 在测评平台登记最终分支和固定 commit，由评审实际执行验证。

题面为六项全通过得 20 分。本机已通过六项条件；最终比赛结果仍以平台评审为准。

## 复现和打包

完整运行说明见 `README.md`，验证样例见 `VALIDATION.md`，一页技术说明见 `ARCHITECTURE.md`。`scripts/package.py` 按 Git 可见文件生成带 SHA-256 清单的源码包，明确排除 `.env`、虚拟环境和运行时数据库。

核对已经完成的真实证据可运行 `python scripts/verify_submission.py evidence/live-final`，预期退出 0；此命令不需要再次调用模型。重新生成代码时，需配置用户自己的 MiniMax 凭据与可用额度。

已保存证据中的本机绝对路径只用于描述当次运行。新环境按说明执行后会生成新的路径、项目 ID、Scope 和 artifact，不依赖现有本机状态。

源码包独立目录检查复用了已安装依赖和真实本地服务，未声称重装了操作系统、Docker 或 Python 依赖。包内 `build-manifest.json` 记录每个文件的 SHA-256 以及生成时的 Git 状态；历史验证记录中的 `dirty=true` 表示当时的文件快照尚未提交，实际内容由文件哈希定位。
