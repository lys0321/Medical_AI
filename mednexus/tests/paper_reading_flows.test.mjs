import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const reading=readFileSync(new URL('../web/paper-reading.js',import.meta.url),'utf8');
const segment=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
class Node {
  constructor(tag='div',cls='',text=''){this.tag=tag;this.className=cls||'';this.textContent=text??'';this.listeners={};this.attrs={};this.hidden=false;this.value='';}
  set textContent(value){this._text=value;this.children=[];}get textContent(){return this._text;}
  set innerHTML(value){assert.equal(value,'');this.children=[];}
  append(...children){children.forEach(child=>this.appendChild(child));}appendChild(child){this.children.push(child);return child;}
  addEventListener(type,fn){this.listeners[type]=fn;}setAttribute(key,value){this.attrs[key]=value;}
  scrollIntoView(){}
}
const all=n=>[n,...n.children.flatMap(all)],text=n=>all(n).map(x=>x.textContent).join(' ');
const button=(root,label)=>all(root).find(n=>n.tag==='button'&&n.textContent===label);
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {resolve,reject,promise};};
const response=()=>({paper:{pmid:'123',title:'Synthetic paper',journal:'Fixture journal',year:'2026'},question:'original question',
  notice:'原文节选，不自动翻译或评价质量',limitations:'局限未识别不代表不存在',relationship:'需核对是否相关',sections:[
    {id:'methods',title:'研究方法',excerpts:[{label:'PATIENTS AND METHODS',category:'METHODS',text:'Verbatim fixture methods.',truncated:true}]},
    {id:'results',title:'研究结果',excerpts:[{label:'RESULTS',category:'RESULTS',text:'Verbatim fixture result.'}]},
    {id:'limitations',title:'研究局限',excerpts:[],missing_notice:'未识别明确局限标签，请核对。'}]});
function setup(api=async()=>response(),context={concept:null,question:'microglia synaptic pruning'}){
  const nodes={},calls=[];const ctx=vm.createContext({researchContext:context,wanderOriginConcept:context?.concept,
    readingRequestId:0,pmRequestId:0,$:id=>nodes[id]??=new Node(),el:(...args)=>new Node(...args),
    api:async(...args)=>{calls.push(args);return api(...args);},rememberResearchWorkspace(){}});
  vm.runInContext(reading,ctx);vm.runInContext(segment('async function loadPaperReading(', '/* ---------- 数据加载 ---------- */'),ctx);
  return {ctx,nodes,calls,load:paper=>ctx.loadPaperReading(paper)};
}

test('independent results offer reading and send the original question without an unrelated course concept',async()=>{
  const s=setup();vm.runInContext(segment('function paperCard(', 'function renderPapers('),s.ctx);
  const card=s.ctx.paperCard({pmid:'123',title:'Synthetic'});assert.ok(button(card,'阅读摘要与证据 →'));
  await button(card,'阅读摘要与证据 →').listeners.click();
  assert.equal(s.calls[0][0],'/api/read-paper');assert.equal(s.calls[0][1].concept,null);
  assert.equal(s.calls[0][1].question,'microglia synaptic pruning');
  assert.ok(!s.nodes.researchReturn);assert.match(text(s.nodes.paperReadingBody),/Verbatim fixture methods/);
});

test('reading shows source labels, exact excerpts, truncation notices, missing sections and canonical PubMed link',()=>{
  const s=setup(),root=new Node(),data=response();data.sections[0].omitted_count=2;data.excerpt_limits={truncated:true};s.ctx.mountPaperReading(root,data);
  const rendered=text(root);assert.match(rendered,/PATIENTS AND METHODS · NLM METHODS/);
  assert.match(rendered,/Verbatim fixture methods/);assert.match(rendered,/开头节选/);assert.match(rendered,/局限未识别不代表不存在/);
  const missing=all(root).find(n=>n.className==='reading-missing');assert.ok(!missing.open);
  assert.match(text(missing),/未识别明确局限标签/);
  assert.equal(all(root).find(n=>n.tag==='a').href,'https://pubmed.ncbi.nlm.nih.gov/123/');
  assert.match(rendered,/另有 2 段未展示/);assert.match(rendered,/未展示不等于原文没有报告/);
});

test('unstructured and missing abstracts never masquerade as inferred results',()=>{
  const s=setup(),root=new Node(),data=response();data.sections=[{id:'unclassified',title:'未分栏摘要',excerpts:[{text:'Unstructured fixture.',label:'',category:'UNASSIGNED'}]}];
  s.ctx.mountPaperReading(root,data);assert.match(text(root),/未分栏摘要/);assert.ok(!text(root).includes('研究结果'));
  data.sections=[];s.ctx.mountPaperReading(root,data);assert.match(text(root),/未取得可展示的摘要/);
});

test('source text and optional AI guide are rendered literally and script source links are not accepted',()=>{
  const s=setup(),root=new Node(),data=response();data.paper.pmid='javascript:alert(1)';data.paper.url='javascript:alert(1)';
  data.sections[0].excerpts[0].text='<img src=x onerror=alert(1)>';
  data.ai_guide={question:'<script>fixture</script>',evidence:'模型解释，待核对'};
  s.ctx.mountPaperReading(root,data);assert.equal(all(root).filter(n=>n.tag==='a').length,0);
  assert.match(text(root),/<img src=x onerror=alert\(1\)>/);assert.match(text(root),/<script>fixture<\/script>/);
  assert.match(text(root),/AI 辅助摘要解读（需对照原摘要核验）/);
});

test('reading failure can retry the same paper and question while detached retry cannot revive an old context',async()=>{
  let failed=true;const s=setup(async()=>{if(failed)throw Error('offline');return response();});
  await s.load({pmid:'123'});const retry=button(s.nodes.paperReadingBody,'重试读取这篇摘要');assert.ok(retry);
  failed=false;await retry.listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(s.calls.length,2);assert.match(text(s.nodes.paperReadingBody),/Synthetic paper/);
  s.ctx.researchContext={concept:'light',question:'other question'};await retry.listeners.click();assert.equal(s.calls.length,2);
});

test('editing a query hides stale papers and invalidates in-flight reading and search without auto querying',async()=>{
  const pending=deferred(),s=setup(()=>pending.promise);
  vm.runInContext(segment('$("pmForm").addEventListener', '$$(".pm-chip")'),s.ctx);
  const readingCall=s.load({pmid:'123'});const before=s.ctx.pmRequestId;
  s.nodes.pmQuery.listeners.input();assert.equal(s.ctx.pmRequestId,before+1);assert.equal(s.nodes.paperReading.hidden,true);
  pending.resolve(response());await readingCall;assert.ok(!text(s.nodes.paperReadingBody).includes('Synthetic paper'));
  assert.equal(s.calls.length,1);assert.match(s.nodes.pmStatus.textContent,/检索式已修改/);
});

/* ---------- 开放获取全文 / 证据字段 / 引文导出 ---------- */

const fulltextResponse=()=>{
  const data=response();
  data.fulltext={available:true,license:'CC BY',pmcid:'PMC123',
    notice:'原文段落，未翻译或改写。',sections:[{id:'results',title:'研究结果',paragraphs:[
      {number:1,text:'We enrolled 120 patients.',citation:'[PMID:1]',truncated:false},
      {number:2,text:'Response was higher.',citation:'[PMID:2]',truncated:true}]}]};
  return data;
};

test('open access full text renders as its own layer with per-paragraph citations',()=>{
  const s=setup(),root=new Node();s.ctx.mountPaperReading(root,fulltextResponse());
  const rendered=text(root);
  assert.match(rendered,/开放获取全文/);assert.match(rendered,/许可：CC BY/);
  assert.match(rendered,/We enrolled 120 patients/);assert.match(rendered,/\[PMID:1\]/);
  assert.match(rendered,/\[PMID:2\]/);assert.match(rendered,/本段仅显示开头/);
});

test('full text is opt-in and loads on demand with the original question and concept',async()=>{
  let asked=null;
  const data=response();data.concept='light';
  data.fulltext={available:false,reason:'not_requested',message:'未请求全文；可以展开开放获取全文。',sections:[]};
  const s=setup(async(path,body)=>{asked={path,body};return fulltextResponse();});
  const root=new Node();s.ctx.mountPaperReading(root,data);
  const load=button(root,'加载开放获取全文');assert.ok(load);
  await load.listeners.click();
  assert.equal(asked.path,'/api/read-paper');
  assert.equal(asked.body.include_fulltext,true);
  assert.equal(asked.body.question,'original question');
  assert.equal(asked.body.concept,'light');
  assert.match(text(root),/We enrolled 120 patients/);
});

test('denied licence shows the reason and never renders full text paragraphs',()=>{
  const data=response();
  data.fulltext={available:false,reason:'license_denied',license:'CC BY-ND',
    message:'该文献的许可不允许摘录正文，只能阅读摘要。',sections:[]};
  const s=setup(),root=new Node();s.ctx.mountPaperReading(root,data);
  const rendered=text(root);
  assert.match(rendered,/不允许摘录正文/);assert.match(rendered,/CC BY-ND/);
  assert.ok(!rendered.includes('We enrolled 120 patients'));
  assert.equal(button(root,'加载开放获取全文'),undefined);
});

test('evidence fields render as checkable hints instead of a quality verdict',()=>{
  const data=response();
  data.evidence_grade={fields:{
      study_type:{status:'reported',value:'随机对照试验',source:'PubMed 文献类型'},
      sample_size:{status:'reported',value:120,source:'摘要原文'},
      randomization:{status:'reported',value:'摘要提到随机化'},
      blinding:{status:'not_reported',value:'',source:'摘要原文'}},
    hints:['摘要未提到盲法：开放标签研究里，主观结局的效应估计更容易偏高。'],
    notice:'以上四项只是可核验字段，不是质量评级。',
    reminder:'不能凭文献类型判定质量。'};
  const s=setup(),root=new Node();s.ctx.mountPaperReading(root,data);
  const rendered=text(root);
  assert.match(rendered,/研究类型：随机对照试验/);assert.match(rendered,/样本量：120/);
  assert.match(rendered,/盲法：摘要未报告/);assert.match(rendered,/不是质量评级/);
  assert.ok(!rendered.includes('高质量'));
});

test('citation buttons export BibTeX or RIS for the current paper',async()=>{
  const asked=[];
  const s=setup(async(path,body)=>{asked.push([path,body]);return {content:'@article{pmid123,'};});
  const root=new Node();s.ctx.mountPaperReading(root,response());
  await button(root,'复制 BibTeX').listeners.click();
  assert.equal(asked[0][0],'/api/export-citations');
  assert.equal(asked[0][1].format,'bibtex');
  assert.deepEqual([...asked[0][1].pmids],['123']);
  assert.match(text(root),/@article\{pmid123/);
  await button(root,'复制 RIS').listeners.click();
  assert.equal(asked[1][1].format,'ris');
});
