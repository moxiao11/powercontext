// Hand-authored, versioned Chinese corpus. No vectors or cached search results.
export const evaluation: {version:string;k:number;documents:Array<{id:string;title:string;text:string}>;queries:Array<{id:string;text:string;relevant:Record<string,number>}>}={version:'tide-zh-1',k:5,documents:[
 {id:'db-hybrid',title:'混合检索的排序机制',text:'混合检索同时利用向量语义相似度与全文关键词匹配。seekdb 在数据库内执行两路召回，并通过 RRF 倒数排名融合生成最终排序。向量可以找到词语不同但含义接近的文档，全文索引能够精确匹配产品名和错误代码。'},
 {id:'db-refresh',title:'增量写入与索引刷新',text:'新文档写入 seekdb 后，需要刷新向量索引以保证搜索可见性。通过 CALL dbms_index_manager.refresh() 建立同步刷新屏障。批量写完后统一刷新通常比每写一条就刷新更快。刷新失败时应保留待刷新状态，允许用户重试。'},
 {id:'db-vector',title:'向量索引 HNSW',text:'HNSW 是一种基于分层图的近似最近邻检索算法。使用余弦距离比较归一化的文本向量，可快速寻找语义相近的内容。向量维度必须与模型输出一致，BGE-small-zh-v1.5 生成 512 维向量。'},
 {id:'gpu-backend',title:'浏览器中的 WebGPU',text:'WebGPU 可以利用用户设备的 GPU 加速浏览器本地神经网络推理。Transformers.js 通过 device: webgpu 显式选择后端，FP16 模型需要 shader-f16 特性。适配器不可用或模型运行失败时，应自动降级到 WebAssembly。'},
 {id:'wasm-fallback',title:'WASM 降级路径',text:'当浏览器不支持 WebGPU 时，ONNX Runtime Web 可以使用 WASM 在 CPU 执行 INT8 模型。开启跨源隔离后可以使用多线程，否则使用单线程。无论采用何种后端，文档向量和查询向量都在用户浏览器本地计算。'},
 {id:'quant-int8',title:'模型 INT8 量化',text:'INT8 量化把原本 FP32 的部分模型权重压缩成 8 位整数，减少文件体积和内存占用。动态量化在推理时计算激活量化参数，无需额外训练。需要用相同的查询集对比 Recall@K 与 nDCG@K，确认精度损失处于可接受范围。'},
 {id:'quant-fp16',title:'半精度浮点模型',text:'FP16 把 32 位浮点张量转换为 16 位浮点表示，理论上可将这些张量的存储减半。转换时可保留输入输出为 FP32，并对不支持半精度的算子保留精度。实际压缩比需要统计转换前后的 ONNX 文件字节数。'},
 {id:'batch-opt',title:'向量化的批处理优化',text:'将多个文本放入同一批次推理可以摊薄调度开销。按文本长度排序并分批，可以减少 padding 的无效计算。模型放在持久化 Web Worker 中复用，避免阻塞页面交互和每次查询重新加载模型。批大小过大也可能导致显存不足。'},
 {id:'cache-load',title:'模型缓存与首次加载',text:'模型首次使用需要下载并建立推理会话，延迟包含网络传输和运行时初始化。后续可以通过浏览器 Cache Storage 缓存模型文件。冷启动、缓存加载、预热和查询耗时应分开记录，重复实验报告中位数而不是最快一次。'},
 {id:'local-privacy',title:'本地推理与数据路径',text:'浏览器端侧推理不调用云端推理 API。模型权重可从公开仓库下载，然后由 WebGPU 或 WASM 在用户设备计算。生成的向量、原文和元数据通过本机 API 写入 seekdb。下载模型不意味着将文档送往远端模型服务。'},
 {id:'kb-session',title:'知识库隔离与会话状态',text:'每个知识库使用独立的 seekdb 集合。前端仅持久化当前集合 ID，服务端使用数据库记录写入版本与已刷新版本。切换集合时清空旧结果，并忽略晚到的旧请求；导入任务固定其目标集合，防止文本误写入其他知识库。'},
 {id:'quality-eval',title:'检索质量评估',text:'Recall@K 衡量前 K 个结果覆盖了多少相关文档，nDCG@K 同时关注相关性等级与排序位置。必须固定语料和人工标注的查询集，对 FP32、FP16、INT8 使用同一套指标。小型自建集只适合回归测试，不能代表公开排行榜表现。'},
 {id:'garden',title:'阳台薄荷种植',text:'薄荷喜欢充足的散射光和湿润土壤，夏季需要适当遮阴。盆栽应注意排水，避免积水导致烂根。定期修剪枝条可以促进侧芽生长。'},
 {id:'coffee',title:'手冲咖啡的水温',text:'手冲咖啡的风味受到水温、研磨度与粉水比影响。浅烘焙豆通常使用较高水温帮助萃取。水流要稳定，避免局部过度萃取造成苦涩。'},
 {id:'travel',title:'城市徒步准备',text:'徒步出行前需要查看天气，准备饮水与舒适的鞋。较长路线应规划休息点，并保留返程时间。夜间出行应选择照明良好的道路。'},
 {id:'cooking',title:'番茄鸡蛋汤',text:'先将番茄切块翻炒出汁，加水煮沸后沿锅边倒入打散的蛋液。关火前加入少量盐和葱花，避免长时间加热导致蛋花变老。'}
],queries:[
 {id:'q01',text:'怎样把关键词与语义搜索的结果融合排序？',relevant:{'db-hybrid':3,'db-vector':1}},
 {id:'q02',text:'新导入的内容搜索不到该怎么办？',relevant:{'db-refresh':3,'kb-session':1}},
 {id:'q03',text:'设备没有 GPU 还能在浏览器里算向量吗？',relevant:{'wasm-fallback':3,'gpu-backend':2}},
 {id:'q04',text:'如何缩小模型文件并检查检索精度是否下降？',relevant:{'quant-int8':3,'quant-fp16':2,'quality-eval':2}},
 {id:'q05',text:'多个文本一起编码怎样减少补齐的开销？',relevant:{'batch-opt':3}},
 {id:'q06',text:'为什么首次使用比后续查询慢？',relevant:{'cache-load':3,'batch-opt':1}},
 {id:'q07',text:'切换知识库如何避免出现上一个集合的结果？',relevant:{'kb-session':3}},
 {id:'q08',text:'我的文档会被发送到云端模型计算吗？',relevant:{'local-privacy':3,'wasm-fallback':1}},
 {id:'q09',text:'使用 16 位浮点数能减少多少模型存储？',relevant:{'quant-fp16':3}},
 {id:'q10',text:'衡量搜索结果覆盖率和排序好坏用什么指标？',relevant:{'quality-eval':3,'quant-int8':1}},
 {id:'q11',text:'余弦距离和 512 维向量索引有什么关系？',relevant:{'db-vector':3}},
 {id:'q12',text:'怎么在阳台上养好薄荷？',relevant:{garden:3}}
]};
