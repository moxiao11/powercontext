import { stat,open } from 'node:fs/promises';
const [url,file]=process.argv.slice(2);
let offset=await stat(file).then(s=>s.size).catch(()=>0), total=Infinity;
const handle=await open(file,'a');
try{while(offset<total){let success=false;for(let attempt=0;attempt<4;attempt++){
 try{const r=await fetch(url,{headers:{Range:`bytes=${offset}-${offset+2*1024*1024-1}`},signal:AbortSignal.timeout(45000)});
 if(r.status===416&&r.headers.get('content-range')===`bytes */${offset}`){total=offset;success=true;break;}
 if(!r.ok)throw Error(`HTTP ${r.status}`);
 const range=r.headers.get('content-range');
 if(r.status===206){const m=range?.match(/bytes (\d+)-(\d+)\/(\d+)/);if(!m||+m[1]!==offset)throw Error('Unexpected Content-Range');total=+m[3];const bytes=new Uint8Array(await r.arrayBuffer());if(bytes.length!==+m[2]-+m[1]+1)throw Error('Truncated range');await handle.write(bytes);offset+=bytes.length;}
 else if(offset===0){const bytes=new Uint8Array(await r.arrayBuffer());await handle.write(bytes);offset=total=bytes.length;}
 else{await r.body.cancel();throw Error('Server did not support resume');}
 console.log(`${file}: ${offset}${isFinite(total)?'/'+total:''} bytes`);success=true;break;
 }catch(e){console.error(`Range retry ${attempt+1}: ${e.message}`)}
 }if(!success)throw Error('Range download failed; rerun to resume');}
}finally{await handle.close();}
