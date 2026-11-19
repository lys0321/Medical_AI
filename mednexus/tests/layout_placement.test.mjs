import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
const html=readFileSync(new URL('../web/index.html',import.meta.url),'utf8');
const app=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const between=(a,b)=>html.slice(html.indexOf(a),html.indexOf(b));
const home=between('id="view-home"','id="view-ask"');
const me=html.slice(html.indexOf('id="view-me"'));
const renderMe=app.slice(app.indexOf('function renderMe('),app.indexOf('function renderProfileCard('));
const refresh=app.slice(app.indexOf('async function refreshOverview()'),app.indexOf('/* ---------- 事件绑定 ---------- */'));

test('home stays clean: pulse compass is not mounted on the first view',()=>{
  assert.ok(!home.includes('pulseMount'),'home must not contain the pulse mount');
  assert.ok(!home.includes('循证学习罗盘'),'home must not show the compass panel');
});

test('personal center hosts the compass and no longer hosts the galaxy',()=>{
  assert.ok(me.includes('pulseMount'),'personal center must contain the pulse mount');
  assert.ok(me.includes('循证学习罗盘'));
  assert.ok(!me.includes('galaxyMount'),'galaxy panel must be removed');
  assert.ok(!me.includes('知识星图'),'galaxy title must be removed');
});

test('renderMe drives the compass from overview pulse and never calls renderGalaxy',()=>{
  assert.match(renderMe,/renderPulse\(mount, data\.pulse/);
  assert.doesNotMatch(renderMe,/renderGalaxy/);
  assert.doesNotMatch(refresh,/renderPulse/,'refreshOverview must not mount the compass on home');
});
