# 独立浏览器与自动降级补测

脚本：`tests/browser-compatibility.mjs`。使用 Playwright 的 `chrome` / `msedge` channel，启动机器上真实安装的浏览器，使用独立临时会话。

```sh
npm run test:browsers
```

每款浏览器按 `auto`、`nogpu`、`gpufail` 顺序执行，共 6 例。无 GPU 会话使用临时进程参数 `--disable-gpu --disable-software-rasterizer`；脚本必须在页面与实际 embedding Worker 中验证无法获取 adapter，否则该用例失败，不能标为降级通过。初始化失败用例只中断本机 FP16 模型文件的请求，确认真实模型加载失败后自动改用 WASM/INT8；不代表 GPU 驱动崩溃或推理中途设备丢失已测试。

每例均真实执行 TXT 文件导入、浏览器 embedding、seekdb 写入与刷新、混合检索、原文查看、重复导入、增量导入及集合切换。所有模型计算均使用应用中的浏览器 Worker；Node 不计算向量，不注入 navigator 模拟值或检索结果。

测试创建带「补测」名称的独立知识库，结束时只清理本轮创建的集合；原始 JSON 与截图保留在 `reports/native-browser/`。也可设置 `KEEP_TEST_BASES=1` 保留本轮集合。记录的浏览器版本必须与测试结论一起呈现，旧版 Edge 的兼容性结果不能冒充最新版验收。

可用环境变量：`BASE_URL`（仅本机地址）、`TIDE_BROWSER_CHANNELS=chrome`、`TIDE_BROWSER_MODES=nogpu`、`HEADED=1`（可见测试窗口）、`EXPECTED_CHROME_VERSION` / `EXPECTED_EDGE_VERSION`（精确版本断言）。默认 headless；脚本显式启用 Chromium sandbox，不修改系统或日常浏览器的设置。Playwright 会给独立测试进程添加其默认自动化参数，完整启动参数可由 `DEBUG=pw:browser` 查看。

Windows PowerShell 可见窗口复现：

```powershell
$env:HEADED='1'
npm run test:browsers
```

运行前按 README 启动数据库、下载模型、构建并启动生产服务。测试命令只控制独立临时会话，不负责安装或升级系统浏览器。部分场景运行也会覆盖 `summary.json`，请先归档需要保留的上一轮记录。

参考：[Playwright 浏览器 channel 文档](https://playwright.dev/docs/browsers)、[Microsoft Edge 的 Playwright 文档](https://learn.microsoft.com/en-us/microsoft-edge/playwright/)。

2026-10-28 已执行：Chrome 156.0.8078.73、Edge 156.0.4314.50，可见窗口 6/6 通过，headless 另 6/6 通过。每例 8 项检查，均真实使用提交应用与本机 seekdb。最终记录见 [补测报告](../reports/native-browser/NATIVE-BROWSER-REPORT.md)；`summary.json` 为最终可见窗口整轮，`headless/` 保存前一轮 JSON。浏览器版本和覆盖范围以记录为准，性能实验仍使用原来的固定浏览器环境。
