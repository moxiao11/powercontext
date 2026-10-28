/// <reference lib="webworker" />
import { env, pipeline } from '@huggingface/transformers';
import { MODEL, type EngineInfo, type ModelConfig, type Precision } from '../../shared/model';
env.allowRemoteModels=false;
env.allowLocalModels=true;
env.localModelPath='/models/';
env.useBrowserCache=true;
env.backends.onnx.wasm!.wasmPaths='/ort/';
// One WASM thread avoids nested-worker restrictions in embedded browser shells.
// Main-thread responsiveness comes from the dedicated embedding Worker.
const threads=1;
env.backends.onnx.wasm!.numThreads=threads;
let extractor:any, info:EngineInfo|undefined, config:ModelConfig={device:'auto',precision:'auto'};
const send=(id:number,type:string,data:unknown)=>self.postMessage({id,type,data});
async function initialize(id:number,next:ModelConfig){
 config=next;
 if(extractor){await extractor.dispose();extractor=undefined;info=undefined;}
 const gpu=(navigator as any).gpu;
 const adapter=await gpu?.requestAdapter().catch(()=>null);
 const available=!!adapter,f16=!!adapter?.features.has('shader-f16');
 let backend:'webgpu'|'wasm'=next.device==='wasm'?'wasm':available?'webgpu':'wasm';
 let precision:Precision=next.precision==='auto'?(backend==='webgpu'?'fp16':'q8'):next.precision;
 let reason=next.device==='wasm'?'手动选择 WASM':available?'WebGPU 适配器可用':'设备未提供 WebGPU，自动降级至 WASM';
 if(next.device==='webgpu'&&!available)throw Error('此环境没有 WebGPU，无法测量该配置。');
 if(backend==='webgpu'&&precision==='fp16'&&!f16){if(next.device==='webgpu')throw Error('GPU 不支持 shader-f16');backend='wasm';precision='q8';reason='GPU 不支持 FP16，自动使用 INT8 + WASM';}
 const start=performance.now();let cached=false;
 try{cached=!!(await caches.match(`/models/${MODEL.id}/onnx/${MODEL.files[precision].name}`)||await caches.match(`https://huggingface.co/${MODEL.id}/resolve/${MODEL.revision}/onnx/${MODEL.files[precision].name}`));}catch{}
 const create=async()=>{
  extractor=await pipeline('feature-extraction',MODEL.id,{revision:MODEL.revision,device:backend,dtype:precision,progress_callback:(p:any)=>{send(id,'progress',{stage:'loading',...p})}});
 };
 try{await create();}
 catch(e){if(backend!=='webgpu'||next.device==='webgpu')throw e;backend='wasm';precision=next.precision==='fp32'?'fp32':'q8';reason=`WebGPU 初始化失败，自动降级 WASM：${String(e)}`;await create();}
 const loadMs=performance.now()-start,warmStart=performance.now();
 try{await extractor('端侧推理预热',{pooling:'cls',normalize:true,truncation:true,max_length:MODEL.maxTokens});}
 catch(e){if(backend!=='webgpu'||next.device==='webgpu')throw e;await extractor.dispose();backend='wasm';precision=next.precision==='fp32'?'fp32':'q8';reason=`WebGPU 执行失败，自动降级 WASM：${String(e)}`;await create();await extractor('端侧推理预热',{pooling:'cls',normalize:true,truncation:true,max_length:MODEL.maxTokens});}
 info={backend,precision,reason,loadMs,warmupMs:performance.now()-warmStart,threads:backend==='wasm'?threads:0,webgpuAvailable:available,shaderF16:f16,cached};
 send(id,'engine',info);return info;
}
async function handle(id:number,type:string,data:any){
 if(type==='clearCache'){await caches.delete('transformers-cache');return {cleared:true};}
 if(type==='init')return initialize(id,data);
 if(type==='embed'){
  if(!extractor)await initialize(id,config);
  const {texts,query=false,batchSize=8}=data;
  const start=performance.now();const vectors:number[][]=Array(texts.length);
  // Group similar lengths to reduce padding; restore original document order.
  const order=texts.map((text:string,i:number)=>({text:query?MODEL.queryPrefix+text:text,i})).sort((a:any,b:any)=>a.text.length-b.text.length);
  for(let p=0;p<order.length;p+=batchSize){
   const batch=order.slice(p,p+batchSize);
   try{const out=await extractor(batch.map((b:any)=>b.text),{pooling:'cls',normalize:true,truncation:true,max_length:MODEL.maxTokens});const rows=out.tolist();batch.forEach((b:any,i:number)=>{vectors[b.i]=rows[i]});}
   catch(e){if(info?.backend!=='webgpu'||config.device!=='auto')throw e;await initialize(id,{device:'wasm',precision:config.precision==='fp32'?'fp32':'q8'});const out=await extractor(batch.map((b:any)=>b.text),{pooling:'cls',normalize:true,truncation:true,max_length:MODEL.maxTokens});batch.forEach((b:any,i:number)=>{vectors[b.i]=out.tolist()[i]});}
   send(id,'progress',{stage:'embedding',completed:Math.min(p+batchSize,texts.length),total:texts.length});
  }
  return {vectors,embeddingMs:performance.now()-start,engine:info};
 }
 throw Error(`Unknown worker operation ${type}`);
}
let queue=Promise.resolve();
self.onmessage=({data:{id,type,data}})=>{queue=queue.then(async()=>{try{send(id,'result',await handle(id,type,data))}catch(e){send(id,'error',e instanceof Error?e.message:String(e))}})};
