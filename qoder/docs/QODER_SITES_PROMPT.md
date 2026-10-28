# 下一步：在 Qoder 中创建并发布展示站

先在仓库的 `qoder/` 目录执行 `python scripts/build_site.py`。
展示站源文件在 `site/`，包含文档和截图的可发布目录在 `dist/site/`。

在个人 Qoder 账号中打开当前仓库，新建任务并引用 `qoder/dist/site/`，可复制以下需求：

```text
请用本账号的 Qoder Sites 创建并发布 LabTrace 项目展示网站。

使用当前工作区 qoder/dist/site/ 的完整内容作为材料；若无法直接导入目录，
请根据其中的 index.html、styles.css、文档、真实运行截图和原创样例创建网站产物。

要求：
1. 保留 LabTrace 的深色视觉、项目简介、科研问题、核心功能、架构、真实截图、验收与运行说明。
2. 代码仓库链接使用 https://github.com/moxiao11/powercontext ，项目目录为 qoder/，
   分支为 2026-competition-ecosystem。
3. 本站为项目展示入口。完整应用需独立启动 FastAPI、seekdb 与 PowerContext；
   不要把静态页面或 localhost 宣称为公开在线工作台。
4. 保留测试数据和真实科研成果的区分，测试结果按 docs/VERIFICATION.md 展示。
5. Qoder 对话文本和原任务截图已归档，按 docs/QODER_DEVELOPMENT_LOG.md 说明真实开发分工，不编造记录。
6. 文档、截图、日志和 PDF 的链接必须在发布后可访问。
7. 创建网站产物并核对预览，通过 Qoder Sites 发布，访问范围选择“任何人可访问”。
   若界面要求本人确认公开访问，请提示我操作。
8. 返回真实发布网址，协助我在未登录窗口验证访问，不使用其他厂商的 Sites 代替。
```

发布成功后，成绩提测表单的“作品链接”填写真实 Qoder Sites HTTPS URL。
`http://127.0.0.1:18999` 是本地预览，不能作为提测链接。

同时回到原 Qoder 开发对话，保存规划、主要实现、调试与测试的原始界面截图或录屏；
在设置 → 个人资料 → 编辑中获取账号 UID。截图索引见 `QODER_DEVELOPMENT_LOG.md`。
