import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Run only against this local app. Each launch uses a new temporary browser profile.
// The script never imports an embedding runtime in Node; all inference is performed
// by the submitted app's real browser Worker and the database is the real seekdb.
const baseURL=process.env.BASE_URL??'http://127.0.0.1:8788';
assert(['localhost','127.0.0.1'].includes(new URL(baseURL).hostname),'Localhost targets only');
const channels=(process.env.TIDE_BROWSER_CHANNELS??'chrome,msedge').split(',');
const modes=(process.env.TIDE_BROWSER_MODES??'auto,nogpu,gpufail').split(',');
assert(channels.every(x=>['chrome','msedge'].includes(x)));
assert(modes.every(x=>['auto','nogpu','gpufail'].includes(x)));
const output=path.resolve('reports/native-browser');
await mkdir(output,{recursive:true});
const health=await fetch(`${baseURL}/api/health`).then(async r=>{const data=await r.json();assert(r.ok&&data.ok,JSON.stringify(data));return data;});
const results=[];
const keepBases=process.env.KEEP_TEST_BASES==='1';
async function deadline(promise,label,timeout=60000){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(`${label} timed out`)),timeout)})]);}finally{clearTimeout(timer);}}

async function detectGPU(scope){
 return scope.evaluate(async()=>{
  let adapter=null,error=null;
  try{adapter=await navigator.gpu?.requestAdapter()??null;}catch(e){error=String(e);}
  return {apiExposed:!!navigator.gpu,adapterAvailable:!!adapter,shaderF16:!!adapter?.features.has('shader-f16'),error};
 });
}
async function runCase(channel,mode){
 const label=`${channel}-${mode}`,created=[],pageErrors=[],requests=[],externalRequests=[],embeddingPayloads=[],injectedFailures=[];
 const result={label,channel,mode,headless:process.env.HEADED!=='1',startedAt:new Date().toISOString(),passed:false,checks:[],database:health.version};
 let browser,context,page;
 const check=(name,evidence)=>result.checks.push({name,passed:true,evidence});
 const args=mode==='nogpu'?['--disable-gpu','--disable-software-rasterizer']:[];
 result.launchArgs=args;
 try{
  const executablePath=channel==='msedge'?process.env.EDGE_TEST_EXECUTABLE:undefined;
  if(executablePath){assert(path.isAbsolute(executablePath),'EDGE_TEST_EXECUTABLE must be an absolute path');result.executablePath=executablePath;}
  browser=await chromium.launch({channel:executablePath?undefined:channel,executablePath,headless:result.headless,chromiumSandbox:true,args,timeout:60000});
  result.browserVersion=browser.version();
  const expectedVersion=channel==='msedge'?process.env.EXPECTED_EDGE_VERSION:process.env.EXPECTED_CHROME_VERSION;
  if(expectedVersion)assert.equal(result.browserVersion,expectedVersion,'Unexpected browser version');
  context=await browser.newContext({viewport:{width:1360,height:960},locale:'zh-CN',timezoneId:'Asia/Shanghai',serviceWorkers:'block'});
  if(mode==='gpufail')await context.route('**/onnx/model_fp16.onnx',async route=>{
   // Real local model fetch failure. No vectors, navigator or database results are mocked.
   injectedFailures.push(route.request().url());await route.abort('failed');
  });
  context.on('request',request=>{
   const url=new URL(request.url());
   if(['http:','https:'].includes(url.protocol)){
    requests.push({method:request.method(),host:url.host,path:url.pathname});
    if(!['localhost','127.0.0.1'].includes(url.hostname))externalRequests.push(url.origin+url.pathname);
   }
   if(request.method()==='POST'&&/\/api\/bases\/[^/]+\/(chunks|search)$/.test(url.pathname)){
    const payload=request.postDataJSON();
    const vectors=payload.vectors??[payload.vector];
    embeddingPayloads.push({path:url.pathname,count:vectors.length,dimensions:vectors.map(v=>v.length),norms:vectors.map(v=>Math.sqrt(v.reduce((s,x)=>s+x*x,0)))});
   }
  });
  page=await deadline(context.newPage(),'Browser page creation');
  page.on('pageerror',error=>pageErrors.push(error.message));
  page.setDefaultTimeout(120000);
  await page.goto(baseURL,{waitUntil:'networkidle'});
  await expect(page.getByRole('button',{name:'创建知识库',exact:true})).toBeEnabled();
  result.userAgent=await page.evaluate(()=>navigator.userAgent);
  result.pageGPU=await detectGPU(page);
  if(mode==='nogpu')assert.equal(result.pageGPU.adapterAvailable,false,'GPU disabling did not actually remove the adapter');
  check('native_browser_launch',{version:result.browserVersion,userAgent:result.userAgent});

  async function createBase(name){
   await page.getByRole('button',{name:'创建知识库',exact:true}).click();
   const dialog=page.getByRole('dialog',{name:'创建知识库',exact:true});
   await dialog.getByRole('textbox',{name:'知识库名称',exact:true}).fill(name);
   const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/bases'&&r.request().method()==='POST');
   await dialog.getByRole('button',{name:'创建知识库',exact:true}).click();
   const body=await (await response).json();
   assert.match(body.id,/^tide_[a-f0-9]{32}$/);created.push(body.id);
   await expect(dialog).toBeHidden();
   await expect(page.getByRole('button',{name:`${name} 0`,exact:true})).toBeEnabled();
   return body.id;
  }
  const baseName=`补测 ${label} ${Date.now()}`;
  const id=await createBase(baseName);
  async function uploadFixture(){
   await page.getByRole('button',{name:'导入文档',exact:true}).click();
   const dialog=page.getByRole('dialog',{name:'导入文档',exact:true});
   await dialog.locator('input[type=file]').setInputFiles(path.resolve('tests/fixtures/acceptance.txt'));
   await dialog.getByRole('button',{name:'开始导入',exact:true}).click();
   await expect(dialog).toBeHidden({timeout:180000});
   await expect(page.getByRole('button',{name:`${baseName} 1`,exact:true})).toBeEnabled();
  }
  await uploadFixture();
  check('file_import_and_refresh','Real TXT uploaded through the app; one document/chunk searchable after refresh');
  const embeddingWorker=page.workers().find(w=>w.url().includes('embedding.worker'));
  assert(embeddingWorker,'Embedding Worker was not observed');
  result.workerGPU=await detectGPU(embeddingWorker);
  result.backend=await page.locator('.stat-card').filter({hasText:'当前推理后端'}).innerText();
  result.backendReason=await page.locator('.backend-reason').innerText();
  if(mode==='nogpu'){
   assert.equal(result.workerGPU.adapterAvailable,false,'Worker still has a GPU adapter');
   assert.match(result.backend,/WASM/);assert.match(result.backend,/INT8/);
   assert.match(result.backendReason,/自动降级|自动使用/);
   check('automatic_wasm_fallback',{page:result.pageGPU,worker:result.workerGPU,backend:result.backend,reason:result.backendReason});
  }else if(mode==='gpufail'){
   assert(result.workerGPU.adapterAvailable&&result.workerGPU.shaderF16,'GPU/FP16 not available; cannot construct this initialization failure');
   assert(injectedFailures.length>0,'FP16 fetch failure was not exercised');
   assert.match(result.backend,/WASM/);assert.match(result.backend,/INT8/);
   assert.match(result.backendReason,/WebGPU 初始化失败.*自动降级 WASM/);
   check('automatic_fallback_after_initialization_failure',{fault:'abort local FP16 file fetch',injectedFailures,backend:result.backend,reason:result.backendReason});
  }else if(result.workerGPU.adapterAvailable&&result.workerGPU.shaderF16&&/WebGPU/.test(result.backend)){
   assert.match(result.backend,/FP16/);check('webgpu_preferred',result.backend);
  }else{
   assert.match(result.backend,/WASM/);check('default_backend_compatibility',{backend:result.backend,reason:result.backendReason});
  }
  async function search(text,expectedText){
   await page.getByRole('textbox',{name:'输入检索问题',exact:true}).fill(text);
   await page.getByRole('button',{name:'开始检索',exact:true}).click();
   await expect(page.locator('.activity')).toBeHidden();
   await expect(page.locator('.result-card').first()).toContainText(expectedText);
   return {query:text,timing:await page.locator('.timing-line').innerText(),endToEnd:await page.locator('.latency').innerText(),topResult:await page.locator('.result-card').first().innerText()};
  }
  result.firstQuery=await search('青岚计划的验收口令是什么？','TIDE-4826');
  await page.getByRole('button',{name:'查看原文',exact:true}).first().click();
  await expect(page.getByRole('dialog',{name:'文档原文',exact:true})).toContainText('TIDE-4826');
  await page.getByRole('button',{name:'关闭原文',exact:true}).click();
  check('hybrid_search_and_original_text',result.firstQuery);
  await uploadFixture();
  check('idempotent_import','Same file imported twice; UI still reports 1 document/chunk');

  await page.getByRole('button',{name:'导入文档',exact:true}).click();
  const importDialog=page.getByRole('dialog',{name:'导入文档',exact:true});
  await importDialog.getByRole('textbox',{name:'文档标题',exact:true}).fill('独立浏览器第二批资料');
  await importDialog.getByRole('textbox',{name:'粘贴文档内容',exact:true}).fill('青岚计划第二阶段的集合切换校验码是 TIDE-5937，新增内容必须在索引刷新后可检索。');
  await importDialog.getByRole('button',{name:'开始导入',exact:true}).click();
  await expect(importDialog).toBeHidden();
  await expect(page.getByRole('button',{name:`${baseName} 2`,exact:true})).toBeEnabled();
  result.incrementalQuery=await search('第二阶段的集合切换校验码是什么？','TIDE-5937');
  check('incremental_import',result.incrementalQuery);
  result.screenshot=path.join(output,`${label}.png`);
  await page.screenshot({path:result.screenshot,fullPage:true});

  await createBase(`${baseName} empty`);
  await page.getByRole('textbox',{name:'输入检索问题',exact:true}).fill('TIDE-5937');
  await page.getByRole('button',{name:'开始检索',exact:true}).click();
  await expect(page.locator('.activity')).toBeHidden();
  await expect(page.getByRole('heading',{name:'检索结果 0',exact:true})).toBeVisible();
  await page.getByRole('button',{name:`${baseName} 2`,exact:true}).click();
  result.restoredQuery=await search('第二阶段的集合切换校验码是什么？','TIDE-5937');
  check('collection_switch_isolation','Empty base returns 0; original base still returns its own documents');
  assert(embeddingPayloads.length>=5,'Expected document and query vectors crossing the API');
  assert(embeddingPayloads.every(p=>p.dimensions.every(d=>d===512)&&p.norms.every(n=>n>0.99&&n<1.01)),'Invalid browser-generated vector payload');
  assert.equal(externalRequests.length,0,`Unexpected external requests: ${externalRequests.join(',')}`);
  assert.deepEqual(pageErrors,[],'Unhandled browser errors');
  result.embeddingPayloads=embeddingPayloads;
  check('browser_vectors_and_local_network',{requests:requests.length,embeddingPayloads:embeddingPayloads.length,externalRequests:0});
  result.passed=true;
 }catch(error){
  result.error=error instanceof Error?error.message:String(error);
  if(page){await page.screenshot({path:path.join(output,`${label}-failure.png`),fullPage:true}).catch(()=>{});result.visibleText=(await page.locator('body').innerText().catch(()=>'' )).slice(0,12000);}
 }finally{
  result.requests=requests;result.externalRequests=externalRequests;result.pageErrors=pageErrors;result.injectedFailures=injectedFailures;
  await context?.close().catch(()=>{});await browser?.close().catch(()=>{});
  result.createdBases=created;result.cleanup=[];
  if(!keepBases)for(const id of created){try{const r=await fetch(`${baseURL}/api/bases/${id}`,{method:'DELETE'});result.cleanup.push({id,ok:r.ok});}catch(error){result.cleanup.push({id,ok:false,error:String(error)});}}
  result.finishedAt=new Date().toISOString();
  await writeFile(path.join(output,`${label}.json`),JSON.stringify(result,null,2));
 }
 return result;
}
for(const channel of channels)for(const mode of modes){
 const r=await runCase(channel,mode);results.push(r);
 console.log(`${r.label}: ${r.passed?'PASS':'FAIL'} ${r.browserVersion??''}${r.error?' '+r.error:''}`);
 await writeFile(path.join(output,'summary.json'),JSON.stringify({at:new Date().toISOString(),baseURL,results,notes:['Installed browser versions are recorded; compatibility success is not proof that a version is the latest.','No-GPU cases must prove both the page and actual embedding Worker cannot obtain a GPU adapter.','No navigator or embedding output is mocked. These smoke timings do not replace the performance benchmark.']},null,2));
}
if(results.some(r=>!r.passed))process.exitCode=1;
