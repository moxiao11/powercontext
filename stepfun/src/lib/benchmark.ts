import { engine } from './engine';
import { api } from './api';
import { chunkDocument } from './chunk';
import { quality } from './metrics';
import { evaluation } from '../data/evaluation';
import { MODEL, SPACE, type ModelConfig } from '../../shared/model';
import type { BenchRow, SearchResponse, Timing } from '../../shared/types';
export const profiles:Array<{name:string;config:ModelConfig;batch:number;writeBatch:number;refreshEach:boolean}>=[
 {name:'FP32 · WASM · 基线',config:{device:'wasm',precision:'fp32'},batch:1,writeBatch:1,refreshEach:true},
 {name:'INT8 · WASM · 优化',config:{device:'wasm',precision:'q8'},batch:8,writeBatch:32,refreshEach:false},
 {name:'FP32 · WebGPU · 基线',config:{device:'webgpu',precision:'fp32'},batch:1,writeBatch:1,refreshEach:true},
 {name:'FP16 · WebGPU · 优化',config:{device:'webgpu',precision:'fp16'},batch:8,writeBatch:32,refreshEach:false},
 {name:'INT8 · WASM · 批处理消融',config:{device:'wasm',precision:'q8'},batch:1,writeBatch:32,refreshEach:false},
 {name:'INT8 · WASM · 刷新消融',config:{device:'wasm',precision:'q8'},batch:8,writeBatch:1,refreshEach:true}
];
export async function runBenchmark(selected:number[],repeats:number,onProgress:(s:string)=>void,onRow:(r:BenchRow)=>void,signal:AbortSignal){
 const failures:Array<{profile:string;repeat:number;error:string}>=[];
 const manifest=await fetch('/models/manifest.json').then(r=>{if(!r.ok)throw Error('请先下载完整模型');return r.json()});
 const chunks=(await Promise.all(evaluation.documents.map(d=>chunkDocument(d.text,d.title,'evaluation',d.id)))).flat();
 for(const pi of selected)for(let repeat=1;repeat<=repeats;repeat++){
  if(signal.aborted)return failures;
  const p=profiles[pi],totalStart=performance.now();let base:string|undefined;
  const check=()=>{if(signal.aborted)throw Error('用户停止评测')};
  try{
   onProgress(`${p.name} · 第 ${repeat}/${repeats} 次 · 加载模型`);
   // Cold Cache Storage on each profile's first repeat; subsequent repeats reuse it.
   if(repeat===1)await engine.clearCache();
   const info=await engine.init(p.config);check();
   base=(await api('/bases',{name:`评测 ${pi+1}-${repeat}`})).id;
   onProgress(`${p.name} · 文档向量化`);
   const embeddings=await engine.embed(chunks.map(c=>c.text),p.batch);check();
   let writeMs=0,refreshMs=0;
   for(let i=0;i<chunks.length;i+=p.writeBatch){check();const out=await api(`/bases/${base}/chunks`,{space:SPACE,chunks:chunks.slice(i,i+p.writeBatch),vectors:embeddings.vectors.slice(i,i+p.writeBatch)});writeMs+=out.writeMs;if(p.refreshEach)refreshMs+=(await api(`/bases/${base}/refresh`,{})).refreshMs;}
   if(!p.refreshEach)refreshMs+=(await api(`/bases/${base}/refresh`,{})).refreshMs;
   const query=async(text:string)=>{check();const t=performance.now(),e=await engine.embed([text],1,true),request=performance.now();const s=await api<SearchResponse>(`/bases/${base}/search`,{space:SPACE,text,vector:e.vectors[0],k:evaluation.k});const timing:Timing={embeddingMs:e.embeddingMs,requestMs:performance.now()-request,searchMs:s.searchMs,endToEndMs:performance.now()-t};return {s,timing}};
   // First DB query reported separately, not included in warm medians.
   const first=await query(evaluation.queries[0].text);
   const queries:BenchRow['queries']=[];
   for(const q of evaluation.queries){onProgress(`${p.name} · 查询 ${queries.length+1}/${evaluation.queries.length}`);const{s,timing}=await query(q.text);const ids=s.hits.map(h=>h.metadata.documentId);queries.push({id:q.id,...timing,...quality(ids,q.relevant,evaluation.k),hits:ids})}
   const file=manifest.files.find((f:any)=>f.file===`onnx/${MODEL.files[info.precision].name}`);
   if(!file)throw Error('缺少模型实际体积记录');
   const row:BenchRow={profile:p.name,repeat,engine:info,batchSize:p.batch,writeBatch:p.writeBatch,refreshStrategy:p.refreshEach?'each-write':'after-import',chunkCount:chunks.length,queryCount:queries.length,embeddingMs:embeddings.embeddingMs,throughput:chunks.length/embeddings.embeddingMs*1000,writeMs,refreshMs,firstQuery:first.timing,queries,recall:queries.reduce((s,x)=>s+x.recall,0)/queries.length,ndcg:queries.reduce((s,x)=>s+x.ndcg,0)/queries.length,modelBytes:file.bytes,totalMs:performance.now()-totalStart};
   onRow(row);
  }catch(e){failures.push({profile:p.name,repeat,error:e instanceof Error?e.message:String(e)});onProgress(`${p.name} · ${String(e)}`);if(signal.aborted)return failures;}
  finally{if(base)await api(`/bases/${base}`,undefined,'DELETE').catch(()=>{});}
 }
 return failures;
}
