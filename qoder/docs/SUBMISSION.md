# 比赛提交入口

项目位于指定比赛分支的 `qoder/`。本地成果和账号侧要求分别如下。

## 本地交付

React 工作台、FastAPI 后端、seekdb 检索与实验记录、PowerContext Memory / Handoff；
原创 Markdown / PDF、实验 JSON、四个演示；运行、架构、集成、验证和部署文档；
真实服务输出与界面截图在 `docs/evidence/`。

## 待完成的真实材料

| 材料 | 状态与操作 |
| --- | --- |
| 比赛私有仓库 | 未提供；现有 origin 是上游代理地址。应推送到导入后的个人比赛仓库 |
| Qoder Sites URL | 未发布。按 `DEPLOYMENT.md` 用个人账号发布并允许任何人访问 |
| Qoder UID | 未提供。在 Qoder 设置 → 个人资料 → 编辑中复制真实 UID |
| Qoder 主要开发记录 | 待核实。提供真实规划、编码、调试对话与截图 |
| 未登录访问验证 | 待发布。无痕窗口打开站点，保存结果 |
| 真实用户效果 | 尚未收集，非基础验收必填。用 `USER_TESTING.md` 记录真实来源 |

本轮工具是 Codex。源码、文件时间和本次验证日志无法证明主要开发在 Qoder 中完成。
若此前没有真实 Qoder 过程，必须在 Qoder 中继续实质开发并保留记录，再评估是否符合赛道要求。
不得改写工具名称、补造截图或声称已经公开发布。

## Windows 启动

先运行 Docker Desktop，在 `qoder/` 执行：

```powershell
# 创建 .env、生成随机认证值并启动，保留已有配置
.\scripts\start.ps1
# 需要独立 seekdb 且默认端口冲突时，在首次初始化时指定端口
.\scripts\start.ps1 -RemoteSeekdb -WebPort 15173 -ApiPort 18100 -PowerContextPort 18010 -SeekdbPort 12881
```

已有 `.env` 的值优先，修改已有端口请编辑该文件。脚本不打印凭据。
Linux / WSL / macOS 启动见 `SETUP.md`。

## 验证、自检与打包

从 `qoder/` 执行，Python 3.11+；演示另需 `httpx`：

```bash
python scripts/e2e_demo.py --api http://127.0.0.1:8100 --keep
cp submission.example.json submission.local.json
# 在本地 JSON 填入真实 URL、UID、截图相对路径、无痕验证结果
python scripts/submission.py check
python scripts/submission.py pack
# 正式提交前严格检查；任何 pending 均返回非零退出码
python scripts/submission.py check --strict
```

`qoder_evidence` 是相对 `qoder/` 的真实截图 / 视频路径数组。
`anonymous_access_verified` 仅在无痕验证成功后设为 `true`。
自检不能替代站点归属、权限和主要开发工具的人工核实。

输出在 `dist/submission/`：源码 ZIP 和 `preflight.json`。ZIP 包含 SHA-256 文件清单，
排除本地环境配置、凭据文件、运行数据、缓存、依赖及构建目录。
ZIP 是补充材料，不能代替包含指定比赛基线历史的完整仓库。

## 分支与提交

```bash
git branch --show-current
# 2026-competition-ecosystem
git merge-base --is-ancestor d647275c308e09b7b623f322a26f5c4e85734fb0 HEAD
# 返回 0
git add qoder/
git commit -m "feat(qoder): complete LabTrace workbench and verification"
git rev-parse HEAD
```

提交前检查无真实凭据，推送到自己的比赛仓库后填报该分支 / commit hash。
工作区未提交改动无法由平台通过 commit hash 获取。
