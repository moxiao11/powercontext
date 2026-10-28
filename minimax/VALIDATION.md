# 可复现验证样例

任务：为 Taskboard 的 `list_tasks` 增加 `status` 筛选。

## 初始数据与原有行为

夹具包含 id 顺序为 `5,2,4,1,3` 的五条任务，状态分别为 `done,doing,done,todo,todo`。修改前实现支持按 id 排序、offset/limit 分页、输入保护与参数校验，尚未实现状态筛选。初始源码和测试完整交付在 `examples/taskboard/project/`。

当前 `REQ-STATUS` 允许 `todo/doing/done`，非法值抛出 ValueError，先筛选再排序分页；`REQ-COMPAT` 要求不传 status 时的排序、分页、默认值、空输入及字典复制行为继续有效。

## 必要上下文来源

| 必须存在的资料 ID | 来源 |
| --- | --- |
| `spec:REQ-STATUS` | `specs/requirements.json` 中对应 ID |
| `spec:REQ-COMPAT` | 同一规格文件中对应 ID |
| `code:taskboard.py` | `taskboard.py` 的 `list_tasks` |
| `test:tests/test_target.py` | 9 个目标功能用例 |
| `test:tests/test_regression.py` | 10 个原有行为回归用例 |
| `test:tests/conftest.py` | 动态加载当前实现及固定初始数据 |

这些路径相对每次运行生成的 `project/`。输出不能包含已经失效的 `ADR-LEGACY` 或无关的 `REQ-BILLING`。

## 操作及预期

1. 按 README 安装依赖、启动 seekdb 与 PowerContext。
2. 执行 `python -m sdd_context demo --mode reference`，记录返回的输出目录。
3. 检查 `context-v1.json` 中旧规格，及 `context-v2.json` 中升级后的 doing 状态、兼容要求和测试来源；旧决策已经退出检索。
4. 检查 `target-before.json` 为退出 1、8 项断言失败、0 环境错误、0 跳过；`regression-before.json` 为 10 项通过。
5. 检查 `before.py`、`after.py` 和 `change.diff`。参考模式修改来自明确标注的本地参考实现。
6. 检查 `target-after-1.json` 为 9 项通过，`regression-after-1.json` 为 10 项通过。前后测试和夹具哈希相同。
7. 检查 `powercontext.jsonl` 的空状态、写入和读取；`state-pointer.json` 只有 scope/artifact 地址。新进程恢复记录在 `resume-*-process.json`，退出码为 0。
8. `resume-before.json` 下一步为 implement，`resume-after.json` 下一步为 review-result，证明恢复状态用于后续处理。
9. `resume-spec-updated.json` 已包含 revision-3 标记，旧验证变为 stale，下一步为 revalidate；重新测试后 `resume-final.json` 为 complete。
10. 检查 `database.jsonl` 中实际 SQL、项目 ID、返回的资料 ID/版本/哈希，以及 `database-history.json` 保留的历史。

每次运行均创建全新目录和随机项目 ID，PowerContext 从空任务状态开始。已交付证据可以阅读核对，但重新执行不依赖它保存的 artifact 或本机路径。

## 真实模型验收

配置真实 MiniMax 凭据后，执行相同命令但使用 `--mode live`。固定测试不变，代码由 MiniMax 根据检索上下文生成。新输出还应包含 `minimax-attempt-*/request.json` 和 `response.json`，并与最终代码差异对应。

运行 `python scripts/verify_submission.py <输出目录>`。参考模式预期返回 1；真实模式只有六项全部通过才返回 0。缺少凭据、模型未生成有效修改或测试失败均不能宣布验收完成。

本次真实验收记录在 `evidence/live-final/`：MiniMax-M2.5 首次生成即通过全部测试，提交检查器返回 0；API 返回代码与 `after.py` 原始字节对应，固定测试及夹具的哈希在修改前后不变。重新核对这些已交付记录不需要模型凭据；需要重新生成代码时才调用真实模式。

## 重置

再次执行 demo 即可得到新的初始工程、数据库项目和任务 Scope。提供 `--output` 时必须使用不存在的目录；现有证据不会被覆盖。无需删除或迁移原有数据库。
