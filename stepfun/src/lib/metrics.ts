export function median(xs:number[]) { if(!xs.length)return 0; const s=[...xs].sort((a,b)=>a-b),i=Math.floor(s.length/2); return s.length%2?s[i]:(s[i-1]+s[i])/2; }
export function quality(ids:string[], relevant:Record<string,number>,k=5){
  const unique=[...new Set(ids.slice(0,k))], positives=Object.entries(relevant).filter(([,v])=>v>0);
  const recall=positives.length?unique.filter(id=>(relevant[id]??0)>0).length/positives.length:0;
  const dcg=(grades:number[])=>grades.reduce((s,g,i)=>s+(2**g-1)/Math.log2(i+2),0);
  const ideal=dcg(positives.map(([,g])=>g).sort((a,b)=>b-a).slice(0,k));
  return {recall,ndcg:ideal?dcg(unique.map(id=>relevant[id]??0))/ideal:0};
}
