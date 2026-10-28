# 潮汐 TIDE｜端侧推理与 seekdb 混合检索

**模型与量化。** 使用公开模型 `Xenova/bge-small-zh-v1.5`，固定 commit `75c43b069aac4d136ba6bc1122f995fedcfd2781`，原模型来自 BAAI。采用上游发布的 FP16 与 INT8 ONNX 图，不训练模型；INT8 配置为 QInt8、per-channel、reduce_range，下载脚本校验 SHA-256。CLS pooling＋L2 归一化，输出 512 维；查询添加模型检索前缀，上限 256 tokens。权重实测 FP32/FP16/INT8 为 94,851,877 / 47,497,427 / 24,010,842 字节，压缩比 1.997× / 3.950×；计入相同 tokenizer/config 的完整包为 95,401,750 / 48,047,300 / 24,560,715 字节，压缩比 1.986× / 3.884×。

**端侧运行。** Transformers.js 3.8.1 在持久化 Web Worker 内执行文档和查询 embedding；显式 `device: webgpu`、`dtype: fp16`，检查适配器与 shader-f16；不可用或自动模式的初始化/执行失败时改用 `device: wasm`、`dtype: q8`。WASM 使用单线程以兼容嵌入式浏览器。界面显示真实选用后端。模型和 WASM 由本机 HTTP 提供，禁用远程模型加载，无云端推理接口，Node 的 embedding 函数主动抛错。

**seekdb。** Node/seekdb-js 1.4.0 连接本地 seekdb 1.4.0。每库独立集合，保存稳定片段 ID、正文、512 维向量及文档 ID/标题/来源/序号；建立 cosine HNSW 与 IK smart 全文索引。`collection.hybridSearch()` 调用数据库 `DBMS_HYBRID_SEARCH`，两路各召回 30 个候选、数据库 RRF(60) 返回 Top K，应用保持数据库次序。32 条批量 upsert 后调用 `CALL dbms_index_manager.refresh()`；刷新成功才更新已刷新版本。存在未刷新写入时拒绝检索。集合注册表、文档表和版本状态也存于 seekdb；全局串行队列避免 SDK 会话变量交叉。

**状态与优化。** 浏览器仅持久化当前集合 ID；切换清空结果并忽略旧请求，导入固定目标集合。文档按 180 Unicode 字符分块、重叠 24，稳定 SHA-256 去重。持久化 Worker、模型缓存、按长度分组、批量推理与统一刷新摊薄开销。

**实测。** 2026-10-28，Windows/i7-14650HX/16GB，默认 GPU 适配器未指定独显；Codex 内置 Chromium，UA Chrome/156.0.0.0。固定 16 文档/12 条分级查询，6 配置各 3 次，共 18 轮；下表为中位数，查询阶段不含首次数据库查询及模型加载。

| 配置（推理批次） | 吞吐 块/s | seekdb ms | 端到端 ms | Recall@5 / nDCG@5 |
|---|---:|---:|---:|---:|
| FP32/WASM（1） | 15.78 | 4.89 | 44.08 | .8889 / .9589 |
| INT8/WASM（8） | 19.90 | 5.19 | 37.44 | .9306 / .9644 |
| FP32/WebGPU（1） | 90.42 | 4.68 | 22.58 | .8889 / .9589 |
| FP16/WebGPU（8） | 366.85 | 5.56 | 27.31 | .9306 / .9644 |

量化在本集上 Recall 增加 4.17 个百分点，nDCG 增加 .0055；小集不足以推广该改善。WebGPU 文档吞吐组合提升 4.06×，查询延迟未改善。INT8/WASM 批大小 1 消融吞吐 16.29，批大小 8 为 19.90，提升约 22.2%；逐条写入/刷新累计刷新 9722 ms，统一刷新为 517 ms，此项含写入批次变化。不得将组合提升全部归因于量化。每组首轮清除模型 Cache Storage、后两轮复用；HTTP 磁盘缓存不清除。模型加载、预热、首次请求、逐条查询、写入及刷新原始数据见 `reports/browser-benchmark.json`；统计口径见 `reports/BENCHMARK.md`。

**验收与复现。** 独立 Chrome 156.0.8078.73、Edge 156.0.4314.50 的 WebGPU 优先、禁用 GPU 后自动 WASM、FP16 文件加载失败后自动 WASM，均完成真实导入与检索；可见窗口与 headless 各 6/6 通过，证据见 `reports/native-browser/`。禁用 GPU 验证页面及实际 Worker 均无 adapter；未测试驱动崩溃或设备丢失。性能表仍来自上面的固定内置 Chromium 环境。使用 `npm ci → npm run db:up → npm run models:download → npm run build → npm start` 启动，`HEADED=1 npm run test:browsers` 补测（PowerShell 设置方法见 `docs/NATIVE-BROWSER-TEST.md`）；性能实验在浏览器性能实验室运行。
