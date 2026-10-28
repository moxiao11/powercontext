# 比赛提交入口

项目位于指定比赛分支的 `qoder/`。本地成果和账号侧要求分别如下。

## 本地交付

React 工作台、FastAPI 后端、seekdb 检索与实验记录、PowerContext Memory / Handoff；
原创 Markdown / PDF、实验 JSON、四个演示；运行、架构、集成、验证和部署文档；
真实服务输出与界面截图在 `docs/evidence/`。

## 材料状态

| 材料 | 状态与操作 |
| --- | --- |
| 比赛仓库 | `https://github.com/moxiao11/powercontext`；推送检查返回 403，用户选择稍后处理写入授权，本地代码尚未推送 |
| Qoder Sites URL | https://labtrace-research-186qw7bzjxs.qoder.zone/ ，已发布，任何人都可访问 |
| Qoder UID / 账号 ID | 已从 Qoder 设置 → 个人资料 → 编辑只读获取，见 QODER_DEVELOPMENT_LOG.md |
| Qoder 主要开发记录 | 用户提供的对话文本及原任务变更、验证截图均已归档，详见 QODER_DEVELOPMENT_LOG.md |
| 未登录访问验证 | 首页及关键资源共 12 项无 Cookie / Authorization 的 HTTP 检查通过，原始记录见 `evidence/site-anonymous-2026-10-28.json`；提交前可再用无痕窗口复核 |
| 真实用户效果 | 尚未收集，非基础验收必填。用 `USER_TESTING.md` 记录真实来源 |

已归档的 Qoder 对话覆盖技术调研、主要后端和前端实现、测试与调试；Codex 后续补全单独记录。
文本原文用于说明开发过程，已有原始对话截图与真实账号 ID 一并归档。
不将本文生成的排版或文本截图当成 Qoder 原始界面证据，也不将本地预览地址当成已发布站点。

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
# 在本地 JSON 填入真实 URL、UID、截图相对路径、匿名访问结果和已推送的 commit
python scripts/submission.py check
python scripts/submission.py pack
# 正式提交前严格检查；任何 pending 均返回非零退出码
python scripts/submission.py check --strict
```

`qoder_evidence` 是相对 `qoder/` 的真实截图 / 视频路径数组。
`anonymous_access_verified` 仅在不带登录凭据的访问验证成功后设为 `true`，保留验证方式与结果。
`pushed_commit` 仅在核对远端分支与本地 HEAD 一致后填写；未推送时严格自检保持 pending。
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

## 成绩提测表单怎么填

| 字段 | 填写内容 |
| --- | --- |
| 代码仓库地址 | 表单已锁定 `https://github.com/moxiao11/powercontext` |
| Branch | `2026-competition-ecosystem` |
| Commit id | 最新且已经推送的完整 commit hash；执行 `git rev-parse HEAD` 获取 |
| 作品链接 | `https://labtrace-research-186qw7bzjxs.qoder.zone/` |

推送与核对（从仓库根目录执行）：

```bash
git push competition HEAD:refs/heads/2026-competition-ecosystem
git rev-parse HEAD
git ls-remote competition refs/heads/2026-competition-ecosystem
```

后两条的 hash 应一致。已有报名分支包含其他赛道提交，合并时应保留，勿强制推送覆盖。

当前 GitHub 写入检查返回 403；用户已选择稍后授权。先完成 Git 客户端写入授权，再推送与核对。
不要在评测平台填写仅存在本机的 commit。

“作品链接”尚未获得时，先按 [Qoder Sites 操作提示](QODER_SITES_PROMPT.md) 发布展示站，再回表单提交。
