// 首页今日计划：闭环补救项应标注来源并套用补救样式，普通项不受影响。
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');
const segment = (a, b) => source.slice(source.indexOf(a), source.indexOf(b));

class Node {
  constructor(tag = 'div', cls = '', text = '') {
    this.tag = tag; this.className = String(cls || ''); this.textContent = String(text || '');
    this.children = []; this.dataset = {}; this.type = ''; this.disabled = false;
  }
  appendChild(n) { this.children.push(n); return n; }
  append(...ns) { ns.forEach((n) => this.children.push(n)); }
  addEventListener(t, fn) { (this._ev ||= {})[t] = fn; }
  querySelectorAll() { return []; }
  setAttribute() {}
  removeChild(n) { const i = this.children.indexOf(n); if (i >= 0) this.children.splice(i, 1); return n; }
}

function setup(plan) {
  const nodes = {};
  const ctx = vm.createContext({
    console, Intl, Date, Math, Number, Array, JSON,
    $: (id) => nodes[id] ??= new Node(),
    el: (tag, cls, text) => new Node(tag, cls, text),
    formatLearningPlanDate: () => '11月20日',
    startLearningPlanTask: () => {},
    showView: () => {},
    toast: () => {},
    learningPlanLoading: false,
  });
  // renderLearningPlan 用到 $$ 做按钮绑定，给个空实现
  ctx.$$ = () => [];
  vm.runInContext(segment('function renderLearningPlan(', 'function shortBook('), ctx);
  ctx.__plan = plan;
  vm.runInContext('renderLearningPlan(__plan)', ctx);
  return { ctx, nodes };
}

const flatten = (n, out = []) => {
  out.push(n);
  (n.children || []).forEach((c) => flatten(c, out));
  return out;
};

test('orchestrated remediation item is labeled and styled', () => {
  const plan = {
    scope: '测试章节', method: '测试', next_due_at: null,
    orchestrated: true,
    counts: { weak: 1, new: 0, due: 0, practiced_today: 0 },
    items: [
      { concept: 'a', name: '知识点A', action: 'review', kind: 'transfer',
        reason: '诊断后变式重测', origin: 'orchestration', weak_points: ['要点一'] },
    ],
  };
  const { nodes } = setup(plan);
  const all = flatten(nodes.learningPlanBody || nodes.learningPlan || Object.values(nodes)[0]);
  const texts = all.map((n) => n.textContent).join('|');
  const classes = all.map((n) => n.className).join(' ');
  assert.match(texts, /诊断后补救/, '应标注为闭环补救项');
  assert.match(classes, /is-remediation/, '应套用补救项样式');
  assert.match(texts, /要点一/, '应显示重点补齐要点');
});

test('ordinary items keep their original labels without remediation style', () => {
  const plan = {
    scope: '测试章节', method: '测试', next_due_at: null,
    counts: { weak: 0, new: 1, due: 0, practiced_today: 0 },
    items: [{ concept: 'b', name: '知识点B', action: 'learn', kind: 'diagnostic', reason: '先测一测' }],
  };
  const { nodes } = setup(plan);
  const all = flatten(nodes.learningPlanBody || nodes.learningPlan || Object.values(nodes)[0]);
  const texts = all.map((n) => n.textContent).join('|');
  const classes = all.map((n) => n.className).join(' ');
  assert.match(texts, /新知识/);
  assert.doesNotMatch(texts, /诊断后补救/);
  assert.doesNotMatch(classes, /is-remediation/);
});
