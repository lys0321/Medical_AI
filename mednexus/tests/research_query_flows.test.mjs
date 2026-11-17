import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('../web/research-query.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const slice=(a,b)=>app.slice(app.indexOf(a),app.indexOf(b));
class Node {
  constructor(tag='div',cls='',value=''){this.tag=tag;this.className=cls||'';this.textContent=value??'';this.value='';this.listeners={};this.hidden=false;}
  set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text;}
  set innerHTML(v){assert.equal(v,'');this.children=[];}
  append(...children){children.forEach(child=>this.appendChild(child));}appendChild(child){this.children.push(child);return child;}
  addEventListener(type,fn){this.listeners[type]=fn;}setAttribute(key,value){this[key]=value;}focus(){}
}
const all=n=>[n,...n.children.flatMap(all)],text=n=>all(n).map(x=>x.textContent).join(' ');
const button=(n,label)=>all(n).find(x=>x.tag==='button'&&x.textContent===label);
const proposal=()=>({query:'oculomotor AND recovery[Title/Abstract]',original_query:'oculomotor AND pupil[Title/Abstract]',
  mode:'focused',mapping:'规则建议，需核对',matches:[{term:'恢复',label:'恢复',query:'recovery[Title/Abstract]'}],
  fallback_reason:'',notice:'不是逐句翻译，比较条件需编辑'});
function setup(api=async()=>({})){
  const nodes={},calls=[];const ctx=vm.createContext({el:(...args)=>new Node(...args),$:id=>nodes[id]??=new Node(),
    api:async(...args)=>{calls.push(args);return api(...args);},pmRequestId:0,readingRequestId:0,
    researchContext:null,wanderOriginConcept:null,overviewData:null,toast(){},renderPapers(){}});
  vm.runInContext(code,ctx);vm.runInContext(slice('function researchSourceLabel', 'async function loadPaperReading'),ctx);
  vm.runInContext(slice('$("pmForm").addEventListener', '$$(".pm-chip")'),ctx);
  return {ctx,nodes,calls};
}

test('proposal shows literal word mapping, original template and a collapsed comparison without a search',()=>{
  const s=setup(),root=new Node();let selected;
  s.ctx.mountResearchQueryPlan(root,proposal(),query=>selected=query);
  assert.match(text(root),/“恢复” → 恢复：recovery/);assert.match(text(root),/不是逐句翻译/);
  assert.ok(!all(root).find(n=>n.tag==='details').open);
  button(root,'恢复原知识点模板').listeners.click();assert.equal(selected,proposal().original_query);
  button(root,'使用焦点建议式').listeners.click();assert.equal(selected,proposal().query);assert.equal(s.calls.length,0);
});

test('fallback does not claim a focus was applied and edited status never overwrites the actual text',()=>{
  const s=setup(),root=new Node(),p=proposal();p.mode='template';p.query=p.original_query;p.fallback_reason='包含多个主题，未自动合并';
  s.ctx.mountResearchQueryPlan(root,p,()=>{});assert.match(text(root),/未自动合并/);assert.ok(!button(root,'使用焦点建议式'));
  s.ctx.updateResearchQueryPlan(root,'manual query');assert.match(text(root),/以文本框中的实际内容为准/);
});

test('detached suggestion buttons cannot alter a new question and supplied text is never interpreted as HTML',()=>{
  const s=setup(),root=new Node(),p=proposal();p.matches[0].term='<img src=x onerror=alert(1)>';let count=0;
  s.ctx.mountResearchQueryPlan(root,p,()=>count++);const old=button(root,'恢复原知识点模板');
  assert.match(text(root),/<img src=x onerror=alert\(1\)>/);
  s.ctx.clearResearchQueryPlan(root);old.listeners.click();assert.equal(count,0);assert.equal(root.children.length,0);
});

test('gate mounts the plan, applying either suggestion only edits the draft, and confirm sends its literal query',async()=>{
  const p=proposal(),s=setup(async(path,body)=>path==='/api/research'?{eligible:true,reason:'可探索',mapping:p.mapping,query:p.query,query_plan:p}:
    {note:body.query,papers:[],count:0});
  s.ctx.$('pmQ').value='动眼神经恢复是否有差异？';
  await s.ctx.pmSearch(s.nodes.pmQ.value,'oculomotor');assert.equal(s.calls.length,1);
  button(s.nodes.researchQueryPlan,'恢复原知识点模板').listeners.click();assert.equal(s.nodes.pmQuery.value,p.original_query);
  assert.equal(s.calls.length,1);assert.match(text(s.nodes.researchQueryPlan),/当前使用原知识点模板/);
  s.nodes.pmQuery.value='oculomotor AND outcome';s.nodes.pmQuery.listeners.input();
  assert.match(text(s.nodes.researchQueryPlan),/手动修改/);assert.equal(s.nodes.pmQuery.value,'oculomotor AND outcome');
  s.nodes.runResearchQuery.listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(s.calls[1][0],'/api/pubmed');assert.equal(s.calls[1][1].query,'oculomotor AND outcome');
  assert.equal(s.calls[1][1].question,'动眼神经恢复是否有差异？');
  assert.ok(!text(s.nodes.researchQueryPlan).includes('尚未向 PubMed 发送'));
});

test('editing the original question removes its mapping and prevents stale controls from restoring it',async()=>{
  const p=proposal(),s=setup(async()=>({eligible:true,reason:'可探索',query:p.query,query_plan:p}));
  s.ctx.$('pmQ').value='动眼神经恢复有差异？';await s.ctx.pmSearch(s.nodes.pmQ.value,'oculomotor');
  const old=button(s.nodes.researchQueryPlan,'恢复原知识点模板');s.nodes.pmQ.value='新的疑问';s.nodes.pmQ.listeners.input();
  old.listeners.click();assert.equal(s.nodes.researchQueryPlan.children.length,0);assert.equal(s.nodes.pmQuery.value,p.query);
  assert.equal(s.calls.length,1);assert.equal(s.nodes.researchQueryEditor.hidden,true);
});

test('applyResearchScope wraps the base in ASCII, replaces modes without stacking and never strips user filters',()=>{
  const s=setup(),base='oculomotor[MeSH]';
  const basic=s.ctx.applyResearchScope(base,'basic',2026);
  assert.equal(basic,'(oculomotor[MeSH]) AND (Review[Publication Type] OR Systematic Review[Publication Type])');
  assert.match(basic,/^[\x00-\x7F]+$/);
  assert.equal(s.ctx.applyResearchScope(basic,'basic',2026),basic);
  const frontier=s.ctx.applyResearchScope(basic,'frontier',2026);
  assert.equal(frontier,'(oculomotor[MeSH]) AND ("2023/01/01"[Date - Publication] : "2026/12/31"[Date - Publication])');
  assert.match(frontier,/^[\x00-\x7F]+$/);
  assert.equal(s.ctx.applyResearchScope(frontier,'basic',2026),basic);
  assert.equal(s.ctx.applyResearchScope(frontier,'frontier',2027),
    '(oculomotor[MeSH]) AND ("2024/01/01"[Date - Publication] : "2027/12/31"[Date - Publication])');
  assert.equal(s.ctx.applyResearchScope(frontier,'none',2026),base);
  assert.equal(s.ctx.applyResearchScope(basic,'none',2026),base);
  assert.equal(s.ctx.applyResearchScope('x AND review[pt]','none',2026),'x AND review[pt]');
  assert.equal(s.ctx.applyResearchScope('x AND review[pt]','basic',2026),
    '(x AND review[pt]) AND (Review[Publication Type] OR Systematic Review[Publication Type])');
  assert.equal(s.ctx.applyResearchScope('x) AND (Review[Publication Type] OR Systematic Review[Publication Type])','none',2026),
    'x) AND (Review[Publication Type] OR Systematic Review[Publication Type])');
});

test('scope buttons rewrite only the draft query, refresh its status and never call the API',()=>{
  const s=setup(),year=new Date().getFullYear();
  s.nodes.pmQuery.value='oculomotor[MeSH]';
  s.nodes.researchScopeBasic.listeners.click();
  assert.equal(s.nodes.pmQuery.value,'(oculomotor[MeSH]) AND (Review[Publication Type] OR Systematic Review[Publication Type])');
  assert.match(s.nodes.pmStatus.textContent,/不保证结果更基础/);
  s.nodes.researchScopeFrontier.listeners.click();
  assert.equal(s.nodes.pmQuery.value,'(oculomotor[MeSH]) AND ("'+(year-3)+'/01/01"[Date - Publication] : "'+year+'/12/31"[Date - Publication])');
  assert.match(s.nodes.pmStatus.textContent,/不保证结果更前沿/);
  s.nodes.researchScopeNone.listeners.click();
  assert.equal(s.nodes.pmQuery.value,'oculomotor[MeSH]');
  assert.match(s.nodes.pmStatus.textContent,/已去掉检索限定/);
  assert.equal(s.calls.length,0);
});

test('ineligible gate offers a way out: independent search and a suggested rephrase, without looping',async()=>{
  const s=setup(async(path,body)=>path==='/api/research'
    ? {eligible:false,reason:'更像概念问题',suggestion:'不同病因的麻痹瞳孔受累是否有差异？',query:'',query_plan:null}
    : {note:body.query||'pupil',papers:[{pmid:'1'}],count:1});
  s.ctx.$('pmQ').value='动眼神经是什么？';
  await s.ctx.pmSearch(s.nodes.pmQ.value,'oculomotor');
  assert.equal(s.calls.length,1);
  // 关键：不能只留一句“先补学”，必须给出可操作的出路。
  const out=button(s.nodes.pmStatus,'按通用医学主题检索');
  assert.ok(out,'ineligible gate must expose an independent-search escape hatch');
  assert.match(text(s.nodes.pmStatus),/不同病因的麻痹瞳孔受累是否有差异/);
  assert.equal(s.nodes.researchQueryEditor.hidden,true);
  out.listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(s.calls.length,2);
  assert.equal(s.calls[1][0],'/api/pubmed');
  assert.equal(s.calls[1][1].concept,undefined,'independent search must not carry the stale concept');
});

test('research source label uses real course/unit/name and never hardcodes a nerve',()=>{
  const s=setup();
  s.ctx.overviewData={course:{name:'系统解剖学'},concepts:[
    {id:'oculomotor',name:'动眼神经的功能与损伤',unit:'眼球运动与瞳孔'},
    {id:'corneal',name:'角膜反射',unit:'脑神经'}]};
  assert.equal(s.ctx.researchSourceLabel('oculomotor'),'来自：系统解剖学 / 眼球运动与瞳孔 / 动眼神经的功能与损伤');
  //  corneal 才属于脑神经；用一个不同 unit 的知识点确保不会串台写死。
  assert.equal(s.ctx.researchSourceLabel('corneal'),'来自：系统解剖学 / 脑神经 / 角膜反射');
  // 元数据缺失时优雅降级，不留空白标签。
  s.ctx.overviewData=null;
  assert.equal(s.ctx.researchSourceLabel('oculomotor'),'来自：当前课程 / oculomotor');
});

test('a failed search still leaves a clickable PubMed escape even when the error has no url',async()=>{
  const s=setup(async()=>{ throw new Error('目前没有这个中文主题的英文检索模板'); });
  const q='间脑的功能是什么';
  await s.ctx.pmSearch(q, null);
  const link=all(s.nodes.pmStatus).find(n=>n.tag==='a');
  assert.ok(link,'failed search must always offer a PubMed link');
  assert.equal(link.href,'https://pubmed.ncbi.nlm.nih.gov/?term='+encodeURIComponent(q));
  assert.match(link.textContent,/搜索这个问题/);
  assert.match(text(s.nodes.pmStatus),/检索失败/);
});

test('when the error carries a url, prefer it over the question fallback',async()=>{
  const wanted='https://pubmed.ncbi.nlm.nih.gov/?term=oculomotor+AND+pupil';
  const s=setup(async()=>{ const e=new Error('PubMed 当前连接失败'); e.url=wanted; throw e; });
  await s.ctx.pmSearch('动眼神经瞳孔', null);
  const link=all(s.nodes.pmStatus).find(n=>n.tag==='a');
  assert.ok(link);
  assert.equal(link.href,wanted);
  assert.match(link.textContent,/打开检索式/);
});
