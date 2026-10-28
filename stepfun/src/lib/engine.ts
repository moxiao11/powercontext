import type { EngineInfo, ModelConfig } from '../../shared/model';
type Progress = { stage:string; file?:string; progress?:number; completed?:number; total?:number };
class Engine {
 private worker:Worker|undefined;private seq=0;
 private pending=new Map<number,{resolve:(v:any)=>void;reject:(e:Error)=>void}>();
 info:EngineInfo|undefined;
 onProgress:(p:Progress)=>void=()=>{};
 onEngine:(e:EngineInfo)=>void=()=>{};
 private call<T>(type:string,data:unknown):Promise<T>{
  if(!this.worker){this.worker=new Worker(new URL('./embedding.worker.ts',import.meta.url),{type:'module'});this.worker.onmessage=({data:{id,type,data}})=>{if(type==='progress')this.onProgress(data);else if(type==='engine'){this.info=data;this.onEngine(data)}else{const p=this.pending.get(id);this.pending.delete(id);if(type==='error')p?.reject(Error(data));else p?.resolve(data)}};this.worker.onerror=e=>{this.pending.forEach(p=>p.reject(Error(e.message)));this.pending.clear();this.worker?.terminate();this.worker=undefined;this.info=undefined;};}
  const id=++this.seq;return new Promise((resolve,reject)=>{this.pending.set(id,{resolve,reject});this.worker!.postMessage({id,type,data})});
 }
 clearCache(){return this.call<{cleared:boolean}>('clearCache',{})}
 init(config:ModelConfig={device:'auto',precision:'auto'}){this.info=undefined;return this.call<EngineInfo>('init',config)}
 async ready(){return this.info??await this.init()}
 embed(texts:string[],batchSize=8,query=false){return this.call<{vectors:number[][];embeddingMs:number;engine:EngineInfo}>('embed',{texts,batchSize,query})}
}
export const engine=new Engine();
