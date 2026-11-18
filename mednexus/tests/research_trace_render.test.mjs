import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('../web/research-trace.js',import.meta.url),'utf8');
class Node {
  constructor(tag='div',cls='',text=''){this.tag=tag;this.className=cls||'';this._text=text??'';this.children=[];this.attrs={};this.style={};this.listeners={};}
  set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text;}
  set innerHTML(v){assert.equal(v,'');this.children=[];}
  append(...c){c.forEach(x=>this.appendChild(x));}appendChild(c){this.children.push(c);return c;}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='class')this.className=String(v);}getAttribute(k){return this.attrs[k];}
  addEventListener(t,f){this.listeners[t]=f;}
}
const all=n=>[n,...n.children.flatMap(all)];
const byClass=(n,c)=>all(n).filter(x=>typeof x.className==='string'&&x.className.split(' ').includes(c));
const text=n=>all(n).map(x=>x.textContent).join(' ');
function setup(){const doc={createElement:tag=>new Node(tag)};const ctx=vm.createContext({document:doc});vm.runInContext(code,ctx);return ctx;}
const trace={
  headline:'从疑问到证据，每一步都留痕',question_label:'干预 / 效果类问题',
  stages:[
    {key:'question',index:1,label:'研究疑问',value:'治疗效果有差异吗？',detail:'干预 / 效果类问题',state:'ready',action:'focus-question'},
    {key:'query',index:2,label:'检索式',value:'term[Title]',detail:'核对后的检索式',state:'ready',action:'focus-query'},
    {key:'evidence',index:3,label:'证据构成',value:'本次检索 2 篇',detail:'不是质量评级',state:'ready',action:'show-evidence'},
    {key:'reading',index:4,label:'逐篇核对',value:'PMID 111、222',detail:'样本量 1 篇',state:'ready',action:'read-paper'},
    {key:'boundary',index:5,label:'结论边界',value:'不产生医学结论',detail:'不能凭类型判断疗效',state:'ready',action:'show-boundary'},
  ],
  checkpoints:[
    {key:'can',label:'现在能核对什么',text:'已取回 2 篇真实记录'},
    {key:'cannot',label:'现在不能推断什么',text:'不能仅凭文献类型判断疗效'},
    {key:'next',label:'下一步动作',text:'先读 1 篇最相关摘要'},
  ],
  audit:{total:2,assessed:2,sample_reported:1,randomization_mentioned:1,blinding_mentioned:1,
    summary:'样本量 1 篇、随机化 1 篇、盲法 1 篇',notice:'未提到不等于原文没有报告。'},
  legal_note:'这是检索与阅读的留痕路线，不是医学结论，也不是证据质量评级。'
};

test('renders five clickable stages with readiness and verifiable values',()=>{
  const ctx=setup(),mount=new Node('div');
  ctx.renderResearchTrace(mount,trace,{onStage:key=>mount.lastKey=key});
  const steps=byClass(mount,'trace-step');
  assert.equal(steps.length,5);
  assert.deepEqual(steps.map(s=>s.getAttribute('data-key')),
    ['question','query','evidence','reading','boundary']);
  assert.match(text(mount),/PMID 111/);
  assert.match(text(steps[0]),/已留痕/);
  steps[3].listeners.click();
  assert.equal(mount.lastKey,'reading');
});

test('pending stages are visible but never filled with invented evidence',()=>{
  const ctx=setup(),mount=new Node('div');
  const partial={...trace,stages:trace.stages.map((s,i)=>i<2?s:{...s,state:'pending',value:'待完成',detail:'尚未取回文献'})};
  ctx.renderResearchTrace(mount,partial,{});
  const pending=byClass(mount,'is-pending');
  assert.equal(pending.length,3);
  assert.match(text(mount),/待完成/);
  assert.ok(!text(mount).includes('PMID 111'));
  assert.match(text(mount),/不是医学结论/);
});

test('empty trace clears mount and returns null',()=>{
  const ctx=setup(),mount=new Node('div');
  mount.appendChild(new Node('p','','旧内容'));
  assert.equal(ctx.renderResearchTrace(mount,null,{}),null);
  assert.equal(mount.children.length,0);
});
