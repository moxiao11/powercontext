import type { Chunk } from '../../shared/types';
export async function sha(text: string) { return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join(''); }
// 180 Unicode characters fits the 256-token budget for Chinese in this model.
export async function chunkDocument(text: string, title: string, source: string, documentId?: string): Promise<Chunk[]> {
  const normalized = text.replace(/\r\n?/g,'\n').normalize('NFC').trim();
  if (!normalized) return [];
  const id = documentId ?? await sha(`${title}\n${normalized}`);
  const chars = Array.from(normalized); const parts: string[] = [];
  for(let start=0;start<chars.length;) {
    let end=Math.min(start+180,chars.length);
    if(end<chars.length){const window=chars.slice(start+110,end);let found=-1;for(let i=0;i<window.length;i++)if(['。','\n','.','；'].includes(window[i]))found=i;if(found>=0)end=start+110+found+1;}
    const part=chars.slice(start,end).join('').trim(); if(part)parts.push(part);
    if(end===chars.length)break; start=Math.max(start+1,end-24);
  }
  return Promise.all(parts.map(async (part,i)=>({id:await sha(`${id}:chunk-v1:${i}:${part}`),text:part,metadata:{documentId:id,title,source,chunk:i,chunks:parts.length,importedAt:new Date().toISOString()}})));
}
