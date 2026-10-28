import { SeekdbClient, Schema, FulltextIndexConfig, VectorIndexConfig } from 'seekdb';
import { randomUUID } from 'node:crypto';
import { MODEL, SPACE } from '../shared/model';
import type { Chunk, KnowledgeBase, SearchResponse } from '../shared/types';

// Fail closed: no embedding package is installed on the API server.
const browserOnlyEmbedding = { name:'stepfun-browser-only', dimension:MODEL.dimension, getConfig:()=>({space:SPACE}), generate:async()=>{throw new Error('Embedding 必须在浏览器中计算；服务器禁止推理。');} };
const createClient=()=>new SeekdbClient({host:process.env.SEEKDB_HOST??'127.0.0.1',port:Number(process.env.SEEKDB_PORT??12883),user:process.env.SEEKDB_USER??'root',password:process.env.SEEKDB_PASSWORD??'',database:process.env.SEEKDB_DATABASE??'stepfun'});
export class Database {
 client = createClient();
 private tail: Promise<unknown> = Promise.resolve();
 private initialized=false;
 // SDK hybridSearch uses session variables. Serializing operations also guards write/refresh visibility.
 run<T>(fn:()=>Promise<T>,readOnly=false):Promise<T>{
  const job=this.tail.catch(()=>{}).then(async()=>{
   try{await this.init();return await fn();}
   catch(error){
    const message=error instanceof Error?error.message:String(error);
    if(!/closed state|connection.*(?:closed|lost)|ECONNRESET|ECONNREFUSED|EPIPE|PROTOCOL_CONNECTION_LOST|ETIMEDOUT/i.test(message))throw error;
    const stale=this.client;this.client=createClient();this.initialized=false;
    try{await stale.close();}catch{}
    // Retry reads once. Never replay an ambiguous create/delete/write operation.
    if(readOnly){await this.init();return fn();}
    throw Object.assign(new Error('数据库连接已断开并已重建，请确认数据库就绪后重试本次操作。'),{status:503});
   }
  });this.tail=job;return job;
 }
 private async init(){if(this.initialized)return;
  await this.client.execute(`CREATE TABLE IF NOT EXISTS tide_bases (id VARCHAR(64) PRIMARY KEY, name VARCHAR(120) NOT NULL, generation BIGINT NOT NULL DEFAULT 0, refreshed_generation BIGINT NOT NULL DEFAULT 0, created_at VARCHAR(40) NOT NULL, space VARCHAR(512) NOT NULL)`);
  await this.client.execute(`CREATE TABLE IF NOT EXISTS tide_documents (base_id VARCHAR(64) NOT NULL, document_id VARCHAR(128) NOT NULL, title VARCHAR(256) NOT NULL, PRIMARY KEY(base_id,document_id))`);
  this.initialized=true;
 }
 async base(id:string){const rows=await this.client.execute('SELECT * FROM tide_bases WHERE id=?',[id]);if(!rows?.length)throw Object.assign(new Error('知识库不存在，请重新选择。'),{status:404});const b=rows[0];if(b.space!==SPACE)throw Error('模型空间与知识库不匹配');return b;}
 async collection(id:string){await this.base(id);return this.client.getCollection({name:id,embeddingFunction:browserOnlyEmbedding});}
 async list():Promise<KnowledgeBase[]>{const rows=await this.client.execute('SELECT * FROM tide_bases ORDER BY created_at ASC');return Promise.all((rows??[]).map(async b=>{const c=await this.collection(b.id);const docs=await this.client.execute('SELECT COUNT(*) AS n FROM tide_documents WHERE base_id=?',[b.id]);return{id:b.id,name:b.name,count:await c.count(),documents:Number(docs?.[0]?.n??0),generation:Number(b.generation),refreshedGeneration:Number(b.refreshed_generation),createdAt:b.created_at,status:Number(b.generation)===Number(b.refreshed_generation)?'ready':'pending'};}));}
 async create(name:string){const id=`tide_${randomUUID().replaceAll('-','')}`;
  const schema=new Schema({fulltextIndex:new FulltextIndexConfig('ik',{ik_mode:'smart'}),vectorIndex:new VectorIndexConfig({hnsw:{dimension:MODEL.dimension,distance:'cosine'},embeddingFunction:browserOnlyEmbedding})});
  await this.client.createCollection({name:id,schema});
  try{await this.client.execute('INSERT INTO tide_bases(id,name,created_at,space) VALUES(?,?,?,?)',[id,name,new Date().toISOString(),SPACE]);}catch(e){await this.client.deleteCollection(id);throw e;}return id;
 }
 async write(id:string,chunks:Chunk[],vectors:number[][]){const c=await this.collection(id);const start=performance.now();
  await this.client.execute('UPDATE tide_bases SET generation=generation+1 WHERE id=?',[id]);
  await c.upsert({ids:chunks.map(c=>c.id),documents:chunks.map(c=>c.text),metadatas:chunks.map(c=>c.metadata),embeddings:vectors});
  for(const ch of new Map(chunks.map(c=>[c.metadata.documentId,c])).values())await this.client.execute('INSERT INTO tide_documents(base_id,document_id,title) VALUES(?,?,?) ON DUPLICATE KEY UPDATE title=VALUES(title)',[id,ch.metadata.documentId,ch.metadata.title]);
  return {writeMs:performance.now()-start,count:await c.count()};
 }
 async refresh(id:string){await this.base(id);const start=performance.now();
  // Explicit synchronous barrier. Do not hide unsupported DB versions behind a success state.
  await this.client.execute('CALL dbms_index_manager.refresh()');
  await this.client.execute('UPDATE tide_bases SET refreshed_generation=generation WHERE id=?',[id]);
  return {refreshMs:performance.now()-start,generation:Number((await this.base(id)).generation)};
 }
 async search(id:string,text:string,vector:number[],k:number):Promise<SearchResponse>{const b=await this.base(id);if(Number(b.generation)!==Number(b.refreshed_generation))throw Object.assign(new Error('新增内容尚未刷新索引，请先点击「刷新索引」。'),{status:409});
  const c=await this.collection(id),start=performance.now();
  // One database hybrid search. No application-side vector/fulltext fusion or reranking.
  const result=await c.hybridSearch({query:{whereDocument:{$contains:text},nResults:Math.max(30,k*4)},knn:{queryEmbeddings:[vector],nResults:Math.max(30,k*4)},rank:{rrf:{rankConstant:60,rankWindowSize:Math.max(30,k*4)}},nResults:k,include:['documents','metadatas']});
  const searchMs=performance.now()-start;
  return {hits:(result.ids[0]??[]).map((hit,i)=>({id:hit,text:result.documents?.[0]?.[i]??'',metadata:result.metadatas?.[0]?.[i] as Chunk['metadata'],rank:i+1,distance:result.distances?.[0]?.[i]??null})),searchMs,generation:Number(b.generation),engine:'seekdb DBMS_HYBRID_SEARCH · RRF(60)'};
 }
 async remove(id:string){await this.base(id);await this.client.deleteCollection(id);await this.client.execute('DELETE FROM tide_documents WHERE base_id=?',[id]);await this.client.execute('DELETE FROM tide_bases WHERE id=?',[id]);}
}
