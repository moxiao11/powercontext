import { mkdir, copyFile, readdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
const require = createRequire(import.meta.url);
const dir=path.resolve(path.dirname(require.resolve('onnxruntime-web')),'..');
await mkdir('public/ort',{recursive:true});
for(const file of await readdir(path.join(dir,'dist'))) if(/\.wasm$|ort-wasm.*\.mjs$/.test(file)) await copyFile(path.join(dir,'dist',file),path.join('public/ort',file));
console.log('ONNX Runtime WASM assets copied to public/ort');
