# 当前提交状态

记录日期：2026-10-27。

源码基于题目指定的 `2026-competition-ecosystem` 分支。上下文模块、数据库检索、PowerContext 状态复用、业务样例、固定测试、演示脚本及说明均已实现。

## 本机已执行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 模块单元测试 | 20 项通过 | `evidence/checks-final/results.log` |
| 真实 seekdb／PowerContext 集成测试 | 5 项通过 | 同上及 `results.xml` |
| 修改前目标测试 | 8 failed、1 passed，环境错误 0 | `evidence/reference-final/target-before.*` |
| 修改后目标测试 | 9 passed | `evidence/reference-final/target-after-1.*` |
| 修改前后回归测试 | 各 10 passed | `evidence/reference-final/regression-*.json` |
| 规格替换、失效项排除、来源定位 | 已验证 | `context-v1.json`、`context-v2.json`、`source-expectations.json` |
| seekdb 工程资料入库及实际查询 | 已验证 | `database.jsonl`、`database-history.json` |
| 空状态保存与新操作系统进程恢复 | 已验证 | `powercontext.jsonl`、`resume-*-process.json` |
| 规格变化使原验证失效，再验证后恢复 | 已验证 | `resume-spec-updated.json`、`resume-final.json` |
| 源码包解压后在独立目录运行完整演示 | 退出 0 | `evidence/clean-source-check.json` |
| 缺少密钥和参考模式不能通过提交检查 | 均按预期阻断 | `evidence/release-checks.json` |

上述业务修改采用明确标注的本地参考实现。完整结果由 `evidence/reference-final/acceptance.json` 记录，`all_six_passed=false`、`submission_ready=false`。

服务曾在中断后停止，一次复测因连接拒绝而失败，记录保留于 `evidence/checks-final-service-unavailable/`；当时尚未执行业务前后对比。恢复服务后重新执行最终验证，环境故障未计作功能失败。

打包审计还发现 Windows 文本写入会转换代码快照的换行。最终实现已改为按原始字节复制前后快照，并在演示中强制核对快照哈希与测试源码哈希；Git 规则保留运行证据的原始字节。修复前记录保留于带 `before-byte-snapshot-fix` 后缀的证据目录。

## 尚待完成的必做项

1. **真实 MiniMax 代码生成／修改。** 用户目前没有 API／Token Plan 凭据。已实现真实适配器，但没有产生真实模型参与记录。配置凭据后，执行 `python -m sdd_context demo --mode live`，再对新运行目录执行 `python scripts/verify_submission.py <目录>`。本地参考实现不替代本项。
2. **参赛私有仓库和平台提交。** 用户目前没有提供私有仓库。作品尚未推送到远端或提交测评平台。获取仓库后，将本地开发分支推送到该私有仓库，并在平台填写最终固定 commit；该提交必须包含真实模型证据。

题面为六项全通过得 20 分、任一项不通过得 0 分。因此当前只能作为已经实现并验证的待补齐作品交付，不能作为完整通过参赛验收的声明。

## 复现和打包

完整运行说明见 `README.md`，验证样例见 `VALIDATION.md`，一页技术说明见 `ARCHITECTURE.md`。`scripts/package.py` 按 Git 可见文件生成带 SHA-256 清单的源码包，明确排除 `.env`、虚拟环境和运行时数据库。

已保存证据中的本机绝对路径只用于描述当次运行。新环境按说明执行后会生成新的路径、项目 ID、Scope 和 artifact，不依赖现有本机状态。

源码包独立目录检查复用了已安装依赖和真实本地服务，未声称重装了操作系统、Docker 或 Python 依赖。包内 `build-manifest.json` 记录每个文件的 SHA-256 以及生成时的 Git 状态；历史验证记录中的 `dirty=true` 表示当时的文件快照尚未提交，实际内容由文件哈希定位。
