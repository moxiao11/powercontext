# Qoder Sites 展示站

`site/` 是项目介绍源文件。发布前构建包含文档和真实截图的完整目录：

```bash
cd qoder
python scripts/build_site.py
# 或提供真实比赛仓库
python scripts/build_site.py --repository-url https://github.com/YOUR_ACCOUNT/YOUR_COMPETITION_REPO
python -m http.server 8899 --directory dist/site
```

浏览器预览 `http://127.0.0.1:8899`。最终发布 **`dist/site/`**，入口为 `index.html`。
本构建只用 Python 标准库，复制展示页、文档、测试证据和原创样例。

展示站与产品实例分开：网站不会连接个人科研数据库，不将静态记录当作在线功能。
完整工作台由 FastAPI、seekdb 和 PowerContext 支撑，按运行说明独立部署。

在个人 Qoder 中引用构建目录，请其使用 Sites 创建网站产物；核对预览后点击发布，
在分享中选择“任何人可访问”，确认公开访问。无痕验证后记录真实 URL。

官方说明：https://docs.qoder.com/qoder/sites
CLI 说明：https://docs.qoder.com/cli/sites

Qoder Sites 支持静态网站及部分含数据库、服务函数和对象存储的 Agent App，能力取决于套餐；
不能据此假定它原生支持运行本项目的 Docker / Python / seekdb 进程。
当前未发布，缺少真实账号及站点权限；不使用其他厂商 Sites 代替。
