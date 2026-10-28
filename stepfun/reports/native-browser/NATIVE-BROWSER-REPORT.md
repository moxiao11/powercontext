# 独立 Chrome / Edge 与自动降级实测

2026-10-28，Windows 11 / Intel Core i7-14650HX / 16 GB；本机提交应用 `http://127.0.0.1:8788`、seekdb 1.4.0。使用 Playwright 1.64.1 控制本机原生安装浏览器，各例独立临时会话，真实应用 Worker 推理和 seekdb 混合检索。

| 浏览器 | 自动优先 | 无 GPU adapter | FP16 初始化失败 |
|---|---|---|---|
| Chrome 156.0.8078.73 | WebGPU / FP16，通过 | 自动 WASM / INT8，通过 | 自动 WASM / INT8，通过 |
| Edge 156.0.4314.50 | WebGPU / FP16，通过 | 自动 WASM / INT8，通过 | 自动 WASM / INT8，通过 |

最终可见窗口整轮 6/6，通过 48 项检查，记录见 [summary.json](summary.json)。此前 headless 另 6/6 通过，原始 JSON 在 `headless/`。每例真实导入 TXT、生成向量、写入并刷新索引、检索口令 TIDE-4826、打开原文、再次导入去重、增量写入并检索 TIDE-5937、新建空集合返回 0、切回原集合重新命中。API 传输的文档与查询向量均为 512 维、L2 范数约 1；未观察到应用会话的外部 HTTP 请求或未处理页面异常。各例仅清理自己创建的两个知识库，清理均成功。

## 降级证据与范围

- `nogpu`：仅在独立浏览器进程添加 `--disable-gpu --disable-software-rasterizer`。页面与实际 embedding Worker 的 `requestAdapter()` 均返回不可用，应用保持自动模式，显示「设备未提供 WebGPU，自动降级至 WASM」，然后完成整个流程。不是手动指定 WASM，也不篡改 navigator。
- `gpufail`：设备真实支持 WebGPU / shader-f16；测试只中断本机 `model_fp16.onnx` 请求，触发真实模型初始化失败。界面显示失败原因与自动 WASM，INT8 文档和查询推理继续成功。此项不代表驱动崩溃、GPU 设备丢失或推理执行中途失败已测试。
- 所有 embedding 都来自浏览器应用 Worker，Node 测试脚本未导入推理运行时、未构造向量或返回假检索结果。没有客户端拼合两路召回，应用仍调用真实 seekdb API。
- `chromiumSandbox: true`；GPU 参数仅影响本轮独立进程。Playwright 自带自动化启动参数，不将此测试描述为完全无参数的日常浏览器会话。
- 本报告验证功能和降级；保留的烟雾测试耗时不替代固定环境下的 18 轮性能实验，也不跨浏览器比较性能。

## 版本来源

Chrome 已安装版为 156.0.8078.73。Google [VersionHistory active releases API](https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/stable/versions/all/releases?filter=endtime=none&order_by=starttime%20desc&pageSize=8) 的原始响应保存于 `chrome-active-releases.json`：.73 正在稳定通道分批推送；同时还列出 .74 和早期 157.0.8103.15 小流量，故不声称本次覆盖了所有分批发布版本。API 字段含义见 [官方说明](https://developer.chrome.com/docs/web-platform/versionhistory/reference)。

Edge 经用户授权使用微软官方 MSI 原地从 132 升级到 156.0.4314.50，安装成功后确认实际启动版本。版本来自 [微软 Stable 元数据](https://edgeupdates.microsoft.com/api/products?view=enterprise)，原始 Windows x64 条目为 `edge-latest-release.json`。安装包 SHA-256 与元数据一致，且 Authenticode 签名有效；安装成功日志在本机忽略的 `.log` 中。安装包和临时浏览器二进制不提交。

## 原始文件与截图

| 场景 | Chrome | Edge |
|---|---|---|
| 自动 WebGPU | [JSON](chrome-auto.json) / [截图](chrome-auto.png) | [JSON](msedge-auto.json) / [截图](msedge-auto.png) |
| 无 GPU 自动 WASM | [JSON](chrome-nogpu.json) / [截图](chrome-nogpu.png) | [JSON](msedge-nogpu.json) / [截图](msedge-nogpu.png) |
| 初始化失败自动 WASM | [JSON](chrome-gpufail.json) / [截图](chrome-gpufail.png) | [JSON](msedge-gpufail.json) / [截图](msedge-gpufail.png) |

`edge-132/` 保存升级前旧版的两例兼容性结果，不计入当前版本验收。`portable-edge-156-setup/` 保存便携 Edge 在加载应用前的崩溃；`setup-version-mismatch/` 保存准备阶段版本不匹配记录。它们不计入最终成功数，也没有伪装为应用通过。`headless/` 仅单独保留该轮 JSON；其中 screenshot 字段记录当时的输出位置，根目录同名图片现为最终可见窗口截图。

复现：按 README 启动后执行 `npm run test:browsers`；PowerShell 中先设置 `$env:HEADED='1'` 可显示测试窗口。脚本与版本断言选项见 [复现说明](../../docs/NATIVE-BROWSER-TEST.md)。
