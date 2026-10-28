import assert from 'node:assert/strict';
import { writeFile,mkdir } from 'node:fs/promises';
import { MODEL,SPACE } from '../shared/model';
import { chunkDocument } from '../src/lib/chunk';
const root=process.env.API_URL??'http://127.0.0.1:8788/api';
const checks:Array<{check:string;passed:boolean}>=[];
async function call(path:string,body?:unknown,method?:string,expected=200){const r=await fetch(root+path,{method:method??(body?'POST':'GET'),headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const result=await r.json();assert.equal(r.status,expected,JSON.stringify(result));return result;}
function unit(i:number){return Array.from({length:MODEL.dimension},(_,j)=>i===j?1:0)}
let a:string|undefined,b:string|undefined;
try{
 const health=await call('/health');assert.equal(health.inference,'browser-only');checks.push({check:'Real seekdb reachable',passed:true});
 a=(await call('/bases',{name:'API disposable integration A'},undefined,201)).id;b=(await call('/bases',{name:'API disposable integration B'},undefined,201)).id;
 const ch=(await Promise.all([chunkDocument('量子潮汐：刷新索引后新增资料可以检索到。','索引手册','test','index'),chunkDocument('浏览器设备本地执行向量化，不调用远程推理。','本地说明','test','local')])).flat();
 await call(`/bases/${a}/chunks`,{space:SPACE,chunks:ch,vectors:[unit(0),unit(1)]});
 await call(`/bases/${a}/search`,{space:SPACE,text:'量子潮汐',vector:unit(1),k:5},undefined,409);checks.push({check:'Unrefreshed writes block search',passed:true});
 await call(`/bases/${a}/refresh`,{});
 let s=await call(`/bases/${a}/search`,{space:SPACE,text:'量子潮汐',vector:unit(1),k:5});assert(s.hits.length>0);assert(s.engine.includes('DBMS_HYBRID_SEARCH'));assert(s.hits.some((h:any)=>h.metadata.documentId==='index'));checks.push({check:'Database hybrid search returns lexical branch despite different vector nearest neighbor',passed:true});
 await call(`/bases/${a}/chunks`,{space:SPACE,chunks:ch,vectors:[unit(0),unit(1)]});await call(`/bases/${a}/refresh`,{});const list=await call('/bases');assert.equal(list.find((x:any)=>x.id===a).count,2);assert.equal(list.find((x:any)=>x.id===a).documents,2);checks.push({check:'Repeated import is idempotent',passed:true});
 const next=await chunkDocument('青岚新资料：增量写入后的专属词语。','第二批','test','incremental');await call(`/bases/${a}/chunks`,{space:SPACE,chunks:next,vectors:[unit(2)]});await call(`/bases/${a}/refresh`,{});s=await call(`/bases/${a}/search`,{space:SPACE,text:'青岚新资料',vector:unit(2),k:5});assert(s.hits.some((h:any)=>h.metadata.documentId==='incremental'));checks.push({check:'Incremental import becomes searchable after barrier',passed:true});
 const other=await chunkDocument('独立知识库里的内容。','B 文档','test','other');await call(`/bases/${b}/chunks`,{space:SPACE,chunks:other,vectors:[unit(0)]});await call(`/bases/${b}/refresh`,{});
 const concurrent=await Promise.all(Array.from({length:8},(_,i)=>call(`/bases/${i%2?a:b}/search`,{space:SPACE,text:i%2?'量子潮汐':'独立',vector:unit(0),k:5})));concurrent.forEach((r,i)=>assert(r.hits.every((h:any)=>i%2?h.metadata.documentId!=='other':h.metadata.documentId==='other')));checks.push({check:'Concurrent collection queries remain isolated',passed:true});
 await call(`/bases/${a}/search`,{space:SPACE,text:'a',vector:[0],k:5},undefined,400);await call(`/bases/${a}/search`,{space:SPACE,text:'a',vector:Array(512).fill(0),k:5},undefined,400);await call(`/bases/${a}/search`,{space:'different-model',text:'a',vector:unit(0),k:5},undefined,400);checks.push({check:'Dimension, zero norm and wrong model rejected',passed:true});
 await mkdir('reports',{recursive:true});await writeFile('reports/api-integration.json',JSON.stringify({at:new Date().toISOString(),database:health.version,note:'Protocol tests use synthetic unit vectors only. These are not inference or benchmark results.',checks},null,2));console.log(`${checks.length} integration checks passed`);
}finally{for(const id of [a,b])if(id)await call(`/bases/${id}`,undefined,'DELETE').catch(e=>console.error(e.message));}
