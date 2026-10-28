import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
const root=process.env.API_URL??'http://127.0.0.1:8788/api';
async function read(path:string){const r=await fetch(root+path,{signal:AbortSignal.timeout(15000)});const body=await r.json();if(!r.ok)throw Error(body.error);return body;}
const before=await read('/bases');
const restarted=spawnSync('docker',['compose','restart','seekdb'],{encoding:'utf8',windowsHide:true});
if(restarted.status!==0)throw Error(restarted.stderr);
let health:any,lastError='';
for(let attempt=0;attempt<40;attempt++){
 try{health=await read('/health');break;}catch(e){lastError=String(e);await new Promise(r=>setTimeout(r,1000));}
}
assert(health?.ok,`Database did not recover: ${lastError}`);
const after=await read('/bases');
const counts=(rows:any[])=>rows.map(b=>({id:b.id,count:b.count,documents:b.documents,generation:b.generation,refreshedGeneration:b.refreshedGeneration})).sort((a,b)=>a.id.localeCompare(b.id));
assert.deepEqual(counts(after),counts(before));
await writeFile('reports/database-restart.json',JSON.stringify({at:new Date().toISOString(),passed:true,checks:['Same API process reconnects after seekdb restart','Collection IDs, document/chunk counts and refresh generations retained'],database:health.version,bases:counts(after)},null,2));
console.log('Database restart: reconnect and persistence passed');
