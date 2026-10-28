# 潮汐 TIDE · 浏览器本地知识库

OceanBase 2026 生态赛「seekdb × 阶跃星辰」实现。所有项目文件均在 `stepfun/`，基于比赛分支原始提交 `d647275c308e09b7b623f322a26f5c4e85734fb0`。

浏览器 Web Worker 运行 BGE-small-zh-v1.5，自动优先 WebGPU/FP16、失败后使用 WASM/INT8。Node 服务仅通过 seekdb-js 收发数据，禁用服务端 embedding。seekdb 内部执行全文＋向量混合检索与 RRF 排序。

## 启动

需要 Node.js 24.5+、Docker Desktop/Engine、Chrome 或 Edge。首次安装和获取模型需要联网；完成后推理所需的模型与 WASM 文件均由本机提供。

在本目录执行：

```sh
npm ci
npm run db:up
npm run models:download
npm run build
npm start
```

打开 <http://127.0.0.1:8788>。开发模式用 `npm run dev`，页面为 <http://127.0.0.1:5178>。模型请先下载完整再进行构建和验收。

默认数据库是 `127.0.0.1:12883/stepfun`，root 空密码，仅映射本机端口，数据保存在 Docker 命名卷 `stepfun-seekdb-data`。镜像通过 digest 锁定为实测 seekdb 1.4.0。数据库通常需要数十秒启动。

使用自己的 seekdb 时，复制 `.env.example` 为 `.env` 修改连接信息；数据库需预先创建，并支持 `DBMS_HYBRID_SEARCH` 与 `dbms_index_manager.refresh()`。不要把数据库密码写入前端。`npm run db:down` 仅停止容器，保留数据；不要删除数据卷。

下载器支持分段续传、Windows 系统代理或 `HTTPS_PROXY`，使用固定模型 commit 并校验三个 ONNX 文件 SHA-256。网络失败可重新执行。`HF_ENDPOINT` 可指定兼容镜像；权重仍必须通过相同 SHA-256 校验。模型文件和依赖不提交 Git，由锁文件与下载脚本复现。

## 使用与验收

1. 创建知识库，导入 UTF-8 TXT、Markdown 或 JSONL；也可粘贴文本或体验内置示例。单文件最多 5MB，单次最多 5000 个分块。
2. JSONL 每行是 `{"title":"标题","text":"正文"}`。正文按 180 个 Unicode 字符分块、24 字符重叠；使用稳定 SHA-256 文档/片段 ID。重复导入相同文件不会增加重复文档。
3. 文档和查询在浏览器本地推理。写入批次为 32，导入完成后建立同步索引刷新屏障；中途失败会保留待刷新状态，可在文档管理中重试刷新。
4. 输入自然语言或关键词；结果显示数据库排名、文本、来源及分块信息，可查看完整片段原文。本应用展示检索证据，不生成大模型回答。
5. 切换知识库清空旧结果。浏览器只保存当前集合 ID；原文、向量、元数据、集合状态均存入 seekdb。
6. 运行设置可明确选择 WASM，验证 CPU 路径；默认自动模式优先 WebGPU。FP16 需要 `shader-f16`。实际后端在页面明确显示。

## 真实评测

进入性能实验室，填写设备信息，选择六个配置、重复 3 次，点击运行，完成后导出原始 JSON。每轮使用独立集合、重新编码全部文档，随后删除临时集合，不使用预先计算的向量或结果。

内置评测为 16 篇中文文档、12 条分级查询，源码与标注在 `src/data/evaluation.ts`。每组记录模型加载/预热、文档编码、写入、刷新、首次查询、后续查询、Recall@5 和 nDCG@5。各配置首轮清除模型 Cache Storage，后两轮复用；HTTP 磁盘缓存不清除。共享模型缓存与首次网络下载不是同一计时范围。

将导出的 JSON 保存为 `reports/browser-benchmark.json`，执行：

```sh
npm run report
npm test
npm run test:integration
```

`report` 生成 `reports/BENCHMARK.md` 与 `benchmark-summary.json`。已经保留本机 18 轮真实浏览器原始数据；[实测报告](reports/BENCHMARK.md) 解释统计口径和限制。API 集成测试使用明确标注的合成单位向量，仅测试数据库协议、刷新、去重、隔离与输入校验，不作为推理/质量实验。

`npm run test:restart` 会真实重启本项目的 seekdb 服务，验证同一 API 进程自动重连、集合计数与索引版本保留。请在没有导入/评测任务运行时单独执行。读取遇到断线会重建 SDK 客户端并重试一次；写入不会自动回放，需用户确认数据库就绪后重试。

`npm run test:browsers` 使用本机独立 Chrome/Edge 和临时会话，自动验证 WebGPU 优先、真实无 adapter 时自动 WASM、FP16 模型加载失败后自动 WASM，以及导入、去重、增量、原文与集合隔离。2026-10-28 实测 Chrome 156.0.8078.73、Edge 156.0.4314.50，可见窗口 6/6、headless 6/6 通过。复现选项见 [独立浏览器补测](docs/NATIVE-BROWSER-TEST.md)，证据见 [补测报告](reports/native-browser/NATIVE-BROWSER-REPORT.md)。这些功能检查不替代原有 18 轮性能数据。

另外完成了独立源码副本的干净安装/构建、固定模型校验及全新 seekdb 数据卷上的首次浏览器流程，见 [启动复现记录](reports/REPRODUCIBILITY.md)。本次复用了已下载的模型文件，不把本地校验描述为全新网络下载。

## 源码与资料

- `src/lib/embedding.worker.ts`：唯一 embedding 推理入口，远程模型加载关闭。
- `server/db.ts`：seekdb-js 集合、批量 upsert、刷新屏障、数据库 RRF 混合检索。
- `src/lib/benchmark.ts`：浏览器原位评测，不在 Node 计算向量。
- `shared/model.ts`：模型 commit、512 维空间、精度文件、SHA-256 与查询前缀。
- `docs/TECHNICAL.pdf`：已检查排版的一页技术说明；`docs/TECHNICAL.md` 为编辑版。
- `reports/`：模型文件实测、浏览器实验、API 验证和验收记录。

模型使用上游公开发布的 FP32、FP16、INT8 ONNX 图，不需要训练。INT8 上游配置为 QInt8、per-channel、reduce_range；配置会随下载记录保留。默认构建只打包前端代码，生产服务从 `public/models` 和 `public/ort` 提供权重及运行时，部署时必须同时保留这两个目录。

技术说明 PDF 可选用 `python scripts/technical-pdf.py` 重新生成（需要 `reportlab`、`pypdf`；非 Windows 设置 `TIDE_PDF_FONT` 指向中文 TTF）。此文档工具不影响 Web 应用启动，也不参与 embedding 推理。

模型来源：[Xenova/BGE 固定版本](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781)，原模型：[BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)。SDK：[oceanbase/seekdb-js](https://github.com/oceanbase/seekdb-js)。性能数据来自 Codex 内置 Chromium；独立 Chrome/Edge 另有完整功能与自动降级记录，版本、测试方法和边界在补测报告中列出。
