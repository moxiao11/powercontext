import { mkdir, readFile, writeFile, rename, stat } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const repo='Xenova/bge-small-zh-v1.5', revision='75c43b069aac4d136ba6bc1122f995fedcfd2781';
const endpoint=(process.env.HF_ENDPOINT || 'https://huggingface.co').replace(/\/$/,'');
const dir=`public/models/${repo}`;
// Node 24 supports HTTPS_PROXY for fetch. On Windows respect the system proxy too.
const downloadEnv={...process.env};
if(process.platform==='win32'&&!downloadEnv.HTTPS_PROXY){const probe=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',"$p=[Net.WebRequest]::DefaultWebProxy.GetProxy([uri]$env:TIDE_ORIGIN);if($p.AbsoluteUri -ne $env:TIDE_ORIGIN){$p.AbsoluteUri}"],{env:{...process.env,TIDE_ORIGIN:endpoint},encoding:'utf8',windowsHide:true});if(probe.status===0&&probe.stdout.trim())downloadEnv.HTTPS_PROXY=probe.stdout.trim();}
const weights=[
 ['onnx/model.onnx',94851877,'69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a'],
 ['onnx/model_fp16.onnx',47497427,'60d0fe5eb8d4e251d4b24dff010a2625c10a013503f0d09f625e8a9b0311315f'],
 ['onnx/model_quantized.onnx',24010842,'15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc']
];
async function hash(file){const h=createHash('sha256');for await(const b of createReadStream(file))h.update(b);return h.digest('hex')}
await mkdir(`${dir}/onnx`,{recursive:true});
const logs=[];
for(const file of ['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','quantize_config.json',...weights.map(x=>x[0])]){
 const target=`${dir}/${file}`, expected=weights.find(x=>x[0]===file), start=performance.now();
 if(expected && await stat(target).then(s=>s.size===expected[1]).catch(()=>false) && await hash(target)===expected[2]){console.log(`Verified existing ${file}`);continue}
 if(!expected&&await stat(target).then(s=>s.size>0).catch(()=>false)){console.log(`Using pinned local ${file}`);continue}
 if(expected&&await stat(`${target}.part`).then(s=>s.size===expected[1]).catch(()=>false)&&await hash(`${target}.part`)===expected[2]){await rename(`${target}.part`,target);console.log(`Verified resumed ${file}`);continue}
 console.log(`Downloading ${file} at pinned revision ${revision}`);
 let success=false;
 for(let attempt=0;attempt<3;attempt++){
  try{const url=`${endpoint}/${repo}/resolve/${revision}/${file}`;
   await new Promise((resolve,reject)=>{const p=spawn(process.execPath,['--use-env-proxy',fileURLToPath(new URL('./download-file.mjs',import.meta.url)),url,`${target}.part`],{env:downloadEnv,stdio:'inherit',windowsHide:true});p.on('error',reject);p.on('exit',code=>code===0?resolve():reject(Error(`download exited ${code}`)));});
   if(expected && ((await stat(`${target}.part`)).size!==expected[1] || await hash(`${target}.part`)!==expected[2]))throw Error('size/SHA256 mismatch');await rename(`${target}.part`,target);success=true;break}catch(e){console.error(`Attempt ${attempt+1}: ${e.message}`)}
 }
 if(!success)throw Error(`Download failed: ${file}. Try setting HF_ENDPOINT=https://hf-mirror.com`);
 logs.push({file,bytes:(await stat(target)).size,sha256:await hash(target),downloadMs:performance.now()-start});
}
const files=[];
for(const [file,,expected]of weights){files.push({file,bytes:(await stat(`${dir}/${file}`)).size,sha256:await hash(`${dir}/${file}`),expected})}
const common=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt'];
const commonBytes=(await Promise.all(common.map(f=>stat(`${dir}/${f}`).then(s=>s.size)))).reduce((a,b)=>a+b,0);
const manifest={repo,revision,measuredAt:new Date().toISOString(),commonBytes,files,downloadLog:logs,quantization:JSON.parse(await readFile(`${dir}/quantize_config.json`,'utf8'))};
await writeFile('public/models/manifest.json',JSON.stringify(manifest,null,2));
await mkdir('reports',{recursive:true});await writeFile('reports/model-sizes.json',JSON.stringify(manifest,null,2));
console.log('All models verified. Measured sizes saved to reports/model-sizes.json');
