import { readFile, writeFile, mkdir } from 'node:fs/promises';
const input=process.argv[2]??'reports/browser-benchmark.json';
const raw=JSON.parse(await readFile(input,'utf8'));
if(raw.schemaVersion!==1||!Array.isArray(raw.rows)||!raw.meta)throw Error('Expected a browser-exported Tide benchmark JSON');
const median=xs=>{if(!xs.length)return null;const s=[...xs].sort((a,b)=>a-b),i=Math.floor(s.length/2);return s.length%2?s[i]:(s[i-1]+s[i])/2;};
const profiles=[...new Set(raw.rows.map(r=>r.profile))];
const summary=profiles.map(profile=>{const rs=raw.rows.filter(r=>r.profile===profile),q=rs.flatMap(r=>r.queries);return {
 profile,repeats:rs.length,backend:rs[0].engine.backend,precision:rs[0].engine.precision,batch:rs[0].batchSize,writeBatch:rs[0].writeBatch,refresh:rs[0].refreshStrategy,
 modelBytes:rs[0].modelBytes,throughput:median(rs.map(r=>r.throughput)),loadMs:median(rs.map(r=>r.engine.loadMs)),coldCacheStorageLoadMs:median(rs.filter(r=>!r.engine.cached).map(r=>r.engine.loadMs)),warmCacheStorageLoadMs:median(rs.filter(r=>r.engine.cached).map(r=>r.engine.loadMs)),warmupMs:median(rs.map(r=>r.engine.warmupMs)),
 embeddingMs:median(rs.map(r=>r.embeddingMs)),writeMs:median(rs.map(r=>r.writeMs)),refreshMs:median(rs.map(r=>r.refreshMs)),firstQueryMs:median(rs.map(r=>r.firstQuery.endToEndMs)),
 queryEmbeddingMs:median(q.map(x=>x.embeddingMs)),searchMs:median(q.map(x=>x.searchMs)),endToEndMs:median(q.map(x=>x.endToEndMs)),recall:median(rs.map(r=>r.recall)),ndcg:median(rs.map(r=>r.ndcg))
};});
const f=x=>x===null?'未测量':x.toFixed(2);
const table=[
 '| 配置 | 次数 | 权重 MB | 吞吐 块/s | 文档编码 ms | 写入 ms | 刷新 ms | 查询编码 ms | seekdb ms | 端到端 ms | Recall@5 | nDCG@5 |',
 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
 ...summary.map(r=>`| ${r.profile} | ${r.repeats} | ${f(r.modelBytes/1e6)} | ${f(r.throughput)} | ${f(r.embeddingMs)} | ${f(r.writeMs)} | ${f(r.refreshMs)} | ${f(r.queryEmbeddingMs)} | ${f(r.searchMs)} | ${f(r.endToEndMs)} | ${r.recall.toFixed(4)} | ${r.ndcg.toFixed(4)} |`)
].join('\n');
const loads=['| 配置 | 首轮清除模型缓存加载 ms | 后续缓存加载 ms | 预热 ms | 首次数据库查询端到端 ms |','|---|---:|---:|---:|---:|',...summary.map(r=>`| ${r.profile} | ${f(r.coldCacheStorageLoadMs)} | ${f(r.warmCacheStorageLoadMs)} | ${f(r.warmupMs)} | ${f(r.firstQueryMs)} |`)].join('\n');
const content=`# 浏览器实测报告\n\n运行时间：${raw.meta.startedAt}\n\n设备：${raw.meta.device}\n\n浏览器 UA：${raw.meta.userAgent}\n\n数据库：${raw.meta.db}\n\n${table}\n\n${loads}\n\n## 口径与限制\n\n- 原始数据：\`${input}\`，由提交应用的浏览器评测页导出；无服务端推理。\n- 固定 ${raw.meta.corpus.documents.length} 篇中文文档、${raw.meta.corpus.queries.length} 条人工分级查询。规模较小，仅证明本集回归表现。\n- 文档吞吐为分块数 / 浏览器编码耗时；各轮统计取中位数。查询延迟是所有轮次预热后查询样本的中位数，首次数据库查询单列。\n- 查询编码不含模型加载；端到端包括 Worker 通信、查询编码、HTTP 往返与响应解析，到前端取得结果时停止，不包括下一帧绘制。\n- 加载包含从本机 HTTP/浏览器缓存读取权重和创建会话；不等同于首次联网下载。各配置首轮清除模型 Cache Storage，后两轮复用；浏览器 HTTP 磁盘缓存未清除。缓存状态与每轮加载记录见原始 JSON。\n- 权重体积统计 ONNX 文件字节数，十进制 MB。共享 tokenizer/config 体积见 model-sizes.json，可另算完整包压缩比。\n- Recall/nDCG 在数据库返回的前 5 个片段内按 documentId 去重，使用固定人工相关性等级。\n- 完整优化配置同时改变精度、推理批次和写入/刷新；不能据此单独归因。INT8 批处理消融保持其他配置一致；刷新消融改变写入批次与刷新频率，属于组合优化。\n- 本次浏览器环境以 UA 为准，不能替代其他 Chrome/Edge 版本和独立 GPU 设备的测试。\n\n## 失败记录\n\n${raw.failures?.length?raw.failures.map(f=>`- ${f.profile} / ${f.repeat}: ${f.error}`).join('\n'):'无。'}\n`;
await mkdir('reports',{recursive:true});
await writeFile('reports/benchmark-summary.json',JSON.stringify({source:input,meta:raw.meta,summary,failures:raw.failures??[]},null,2));
await writeFile('reports/BENCHMARK.md',content);
console.log(table);
