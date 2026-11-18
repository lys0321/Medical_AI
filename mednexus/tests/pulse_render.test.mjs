import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('../web/pulse.js',import.meta.url),'utf8');

class Node {
  constructor(tag='div',cls='',text=''){this.tag=tag;this.className=cls||'';this._text=text??'';this.children=[];this.attrs={};this.style={};this.listeners={};}
  set textContent(v){this._text=v;this.children=[];}get textContent(){return this._text;}
  set innerHTML(v){assert.equal(v,'');this.children=[];}
  append(...c){c.forEach(x=>this.appendChild(x));}appendChild(c){this.children.push(c);return c;}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='class')this.className=String(v);}getAttribute(k){return this.attrs[k];}
  addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f);}
  fire(t,ev={}){(this.listeners[t]||[]).forEach(f=>f(ev));}
}
const all=n=>[n,...n.children.flatMap(all)];
const byClass=(n,c)=>all(n).filter(x=>typeof x.className==='string'&&x.className.split(' ').includes(c));
function setup(handlers={}){
  const doc={createElementNS:(ns,tag)=>new Node(tag),createElement:tag=>new Node(tag),
             createTextNode:t=>new Node('#text','',String(t))};
  const ctx=vm.createContext({document:doc,Math,encodeURIComponent,handlers});
  vm.runInContext(code,ctx);
  return ctx;
}
const P={
  index:72,level:'积累',
  dimensions:[
    {key:'evidence',label:'循证提问',value:80,detail:'4/5 次提问带教材依据',note:'看的是出处，不是数量。'},
    {key:'mastery',label:'掌握质量',value:67,detail:'2/3 个已测评知识点达标',note:'未测评不扣分。'},
    {key:'loop',label:'闭环补救',value:33,detail:'3 个需巩固点，1 个已排入今日补救',note:'不代表已掌握。'},
    {key:'consistency',label:'学习节奏',value:71,detail:'连续 5 天 · 累计活跃 12 天',note:'只看前台计时。'},
  ],
  headline:'你的「循证提问」表现稳定；「闭环补救」还有提升空间。这是行为观察，不是成绩排名。',
  disclaimer:'这是本机学习行为的诚实观察，不是能力评分，也不代表医学水平。',
  source:'本地真实作答与提问数据',
};

test('renders a light SVG compass with one arc per dimension',()=>{
  const ctx=setup(),root=new Node('div');
  const svg=ctx.renderPulse(root,P);
  assert.ok(svg,'svg returned');
  assert.match(svg.className,/pulse-svg/);
  const arcs=byClass(svg,'pulse-arc');
  assert.equal(arcs.length,4,'one arc per dimension');
  assert.deepEqual(arcs.map(a=>a.getAttribute('data-key')),['evidence','mastery','loop','consistency']);
});

test('arc dasharray reflects value; unmeasured dimensions draw no arc',()=>{
  const ctx=setup(),root=new Node('div');
  const p=JSON.parse(JSON.stringify(P));
  p.dimensions[2].value=null; // loop unmeasured
  ctx.renderPulse(root,p);
  const arcs=byClass(root,'pulse-arc');
  const loop=arcs.find(a=>a.getAttribute('data-key')==='loop');
  assert.equal(loop.getAttribute('data-value'),'null');
  const dash=loop.getAttribute('stroke-dasharray');
  assert.ok(dash.startsWith('0 '),'unmeasured arc must have zero length: '+dash);
  const ev=arcs.find(a=>a.getAttribute('data-key')==='evidence');
  assert.ok(!byClass(ev,'is-unmeasured').length);
  assert.ok(!ev.getAttribute('stroke-dasharray').startsWith('0 '));
});

test('center shows the index when present and a dash when unmeasured',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderPulse(root,P);
  assert.equal(byClass(root,'pulse-index')[0]._text,'72');
  assert.equal(byClass(root,'pulse-level')[0]._text,'积累');
  const root2=new Node('div');
  const p2={...P,index:null,level:'尚未开始'};
  ctx.renderPulse(root2,p2);
  assert.equal(byClass(root2,'pulse-index')[0]._text,'—');
});

test('each dimension is a labelled, clickable row carrying honest detail',()=>{
  let inspected=null;
  const ctx=setup({onInspect:(k)=>inspected=k}),root=new Node('div');
  ctx.renderPulse(root,P);
  const rows=byClass(root,'pulse-dim');
  assert.equal(rows.length,4);
  const ev=rows[0];
  assert.match(all(ev).map(n=>n._text||'').join(' '),/循证提问/);
  assert.match(all(ev).map(n=>n._text||'').join(' '),/4\/5/);
  ev.fire('click');
  assert.equal(inspected,'evidence');
});

test('honest disclaimer and source are always rendered',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderPulse(root,P);
  const txt=all(root).map(n=>n._text||'').join(' ');
  assert.match(txt,/不是能力评分/);
  assert.match(txt,/本地真实/);
  assert.match(txt,/行为观察/);
});

test('empty data degrades gracefully with no fabricated score',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderPulse(root,null);
  assert.equal(byClass(root,'pulse-index')[0]._text,'—');
  assert.equal(byClass(root,'pulse-dim').length,4,'still shows four empty dimensions');
});

test('does not mutate input',()=>{
  const ctx=setup(),root=new Node('div');
  const before=JSON.stringify(P);
  ctx.renderPulse(root,P);
  assert.equal(JSON.stringify(P),before);
});
