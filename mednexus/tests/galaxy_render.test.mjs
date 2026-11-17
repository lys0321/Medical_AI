import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('../web/galaxy.js',import.meta.url),'utf8');
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
function setup(){
  const doc={createElementNS:(ns,tag)=>new Node(tag),createElement:tag=>new Node(tag),
             createTextNode:t=>new Node('#text','',String(t))};
  const ctx=vm.createContext({document:doc,Math,encodeURIComponent,
    onOpen:()=>{},onInspect:()=>{}});
  vm.runInContext(code,ctx);
  return ctx;
}
const G={viewBox:[0,0,680,460],center:[340,230],
  clusters:[{unit:'单元一',count:2,ring:74,center:[340,230]},{unit:'单元二',count:1,ring:136,center:[340,230]}],
  nodes:[
    {id:'a',name:'动眼神经',unit:'单元一',cluster:0,status:'已掌握',score:92,attempts:3,tone:'mastered',is_weak:false,x:340,y:156,r:16,cluster_ring:74},
    {id:'b',name:'瞳孔反射',unit:'单元一',cluster:0,status:'需巩固',score:55,attempts:2,tone:'weak',is_weak:true,x:400,y:250,r:12,cluster_ring:74},
    {id:'c',name:'展神经',unit:'单元二',cluster:1,status:'未测评',score:null,attempts:0,tone:'untested',is_weak:false,x:476,y:230,r:9,cluster_ring:136},
  ],
  summary:{total:3,mastered:1,weak:1,assessed:2,pages_reviewed:0,has_weak:true,source:'本地真实作答数据'}};

test('renders an svg with orbit rings for every cluster',()=>{
  const ctx=setup(),root=new Node('div');
  const out=ctx.renderGalaxy(root,G);
  assert.ok(out);
  const svg=byClass(root,'galaxy-svg')[0];
  assert.ok(svg,'a galaxy svg is rendered');
  assert.equal(svg.getAttribute('viewBox'),'0 0 680 460');
  const orbits=byClass(svg,'galaxy-orbit');
  assert.equal(orbits.length,2,'one orbit per cluster');
  assert.equal(orbits[0].getAttribute('r'),'74');
});

test('each node carries status tone, verifiable data and a click handler',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderGalaxy(root,G,{onOpen:id=>ctx.__opened=id});
  const dots=byClass(root,'galaxy-node');
  assert.equal(dots.length,3);
  const weak=dots.find(n=>n.getAttribute('data-id')==='b');
  assert.match(weak.className,/tone-weak/);
  assert.ok(byClass(weak,'galaxy-pulse').length,'weak node has an attention pulse');
  assert.equal(weak.getAttribute('data-status'),'需巩固');
  assert.equal(weak.getAttribute('data-score'),'55');
  assert.ok(weak.listeners.click,'node is clickable');
  weak.listeners.click();
  assert.equal(ctx.__opened,'b','click routes back to the real concept');
});

test('center encodes real mastery counts and source is honest',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderGalaxy(root,G);
  const txt=all(root).map(n=>n.textContent).join(' ');
  assert.match(txt,/1\s*\/\s*3/,'mastered over total shown');
  assert.match(txt,/本地真实作答数据/,'source is labeled as real local data');
  assert.ok(byClass(root,'galaxy-weak-legend')[0],'weak legend present when has_weak');
});

test('empty galaxy degrades gracefully without fake stars',()=>{
  const ctx=setup(),root=new Node('div');
  const out=ctx.renderGalaxy(root,{...G,nodes:[],clusters:[],summary:{...G.summary,total:0,has_weak:false}});
  assert.equal(byClass(root,'galaxy-node').length,0);
  const txt=all(root).map(n=>n.textContent).join(' ');
  assert.match(txt,/还没有测评数据|开始第一次测评/);
});

test('untested stars glow softly but never pulse as weak',()=>{
  const ctx=setup(),root=new Node('div');
  ctx.renderGalaxy(root,G);
  const untested=byClass(root,'galaxy-node').find(n=>n.getAttribute('data-id')==='c');
  assert.match(untested.className,/tone-untested/);
  assert.equal(byClass(untested,'galaxy-pulse').length,0,'untested must not be marked weak');
  assert.equal(untested.getAttribute('data-score'),'','no fabricated score');
});
