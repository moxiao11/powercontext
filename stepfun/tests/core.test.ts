import { describe,it,expect } from 'vitest';
import { quality,median } from '../src/lib/metrics';
import { chunkDocument } from '../src/lib/chunk';
describe('ranking metrics',()=>{
 it('uses all relevant documents as recall denominator and graded nDCG',()=>{expect(quality(['b','a'],{a:3,b:1,c:2},2).recall).toBeCloseTo(2/3);expect(quality(['a','b'],{a:3,b:1},2).ndcg).toBe(1);expect(quality(['b','a'],{a:3,b:1},2).ndcg).toBeLessThan(1)});
 it('does not count duplicate chunks or documents beyond the cutoff',()=>{expect(quality(['a','a','b'],{a:1,b:1},2).recall).toBe(0.5);expect(quality([],{a:1}).ndcg).toBe(0)});
 it('reports median without mutating raw samples',()=>{const xs=[90,1,5,4];expect(median(xs)).toBe(4.5);expect(xs).toEqual([90,1,5,4])});
});
describe('document identity and chunking',()=>{
 it('is idempotent and preserves unicode without oversized chunks',async()=>{const text='甲乙😀。'.repeat(170);const a=await chunkDocument(text,'test','file'),b=await chunkDocument(text,'test','file');expect(a.map(c=>c.id)).toEqual(b.map(c=>c.id));expect(a.every(c=>Array.from(c.text).length<=180)).toBe(true);expect(a.length).toBeGreaterThan(1);expect(a.at(-1)?.text.endsWith('。')).toBe(true);expect(a.every(c=>!c.text.includes('\ufffd'))).toBe(true)});
 it('normalizes line endings and distinguishes documents with different content',async()=>{const a=await chunkDocument('a\r\nb','same','a'),b=await chunkDocument('a\nb','same','b'),c=await chunkDocument('other','same','a');expect(a[0].id).toBe(b[0].id);expect(a[0].metadata.documentId).not.toBe(c[0].metadata.documentId);expect(await chunkDocument('  ','x','x')).toEqual([])});
});
