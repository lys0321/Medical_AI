import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const app=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const slice=(a,b)=>app.slice(app.indexOf(a),app.indexOf(b));
class Node {
  constructor(tag='div',cls='',value=''){this.tag=tag;this.className=cls||'';this._text=value??'';this.value='';this.listeners={};this.children=[];this.attrs={};this.style={};}
  set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text;}
  set innerHTML(v){assert.equal(v,'');this.children=[];}
  append(...c){c.forEach(x=>this.appendChild(x));}appendChild(c){this.children.push(c);return c;}
  addEventListener(t,f){this.listeners[t]=f;}setAttribute(k,v){this.attrs[k]=v;}
}
const all=n=>[n,...n.children.flatMap(all)],text=n=>all(n).map(x=>x.textContent).join(' ');
function setup(){
  const ctx=vm.createContext({el:(...a)=>new Node(...a),document:{createTextNode:t=>{const n=new Node('#text','',String(t));return n;}}});
  vm.runInContext(slice('function evidenceMixBar', 'function renderPapers'),ctx);
  return ctx;
}

test('empty mix renders nothing',()=>{
  const ctx=setup();
  assert.equal(ctx.evidenceMixBar(null),null);
  assert.equal(ctx.evidenceMixBar({total:0,buckets:[]}),null);
});

test('stack segments carry width=percent and title with exact counts',()=>{
  const ctx=setup();
  const mix={total:4,summary:'本次检索 4 篇：系统综述/Meta 1 篇、随机对照试验 2 篇、病例报告 1 篇。',
    notice:'以上只是按 PubMed 官方文献类型统计，不是证据质量评级。',
    buckets:[{key:'meta',label:'系统综述/Meta',count:1,percent:25},
             {key:'rct',label:'随机对照试验',count:2,percent:50},
             {key:'case',label:'病例报告',count:1,percent:25}],
    has_primary:true,has_synthesis:true};
  const bar=ctx.evidenceMixBar(mix);
  const segs=all(bar).filter(n=>typeof n.className==='string'&&n.className.split(' ').includes('evidence-seg'));
  assert.equal(segs.length,3);
  assert.equal(segs[0].style.width,'25%');
  assert.equal(segs[1].style.width,'50%');
  assert.match(segs[1].title,/随机对照试验 2 篇/);
  // 描述性汇总与"不是质量评级"声明都要可见
  assert.match(text(bar),/本次检索 4 篇/);
  assert.match(text(bar),/不是证据质量评级/);
});

test('mix is grounded in official types and never renders a prescriptive verdict',()=>{
  const ctx=setup();
  const mix={total:2,summary:'本次检索 2 篇：病例报告 2 篇。',notice:'以上只是按 PubMed 官方文献类型统计，不是证据质量评级，不能替代偏倚风险评估。',
    buckets:[{key:'case',label:'病例报告',count:2,percent:100}],has_primary:true,has_synthesis:false};
  const bar=ctx.evidenceMixBar(mix);
  const rendered=text(bar);
  for(const word of ['建议','首选','应信任','高质量','推荐等级']) assert.ok(!rendered.includes(word));
  assert.match(rendered,/PubMed 官方|PubMed/);
});
