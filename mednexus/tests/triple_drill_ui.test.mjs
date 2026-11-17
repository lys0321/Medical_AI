// 三要点自测前端流程：模式切换、逐要点选择、结果渲染与提交。
// 沿用项目既有的 vm 沙箱 + 文本 Node 风格，不依赖浏览器与网络。
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../web/app.js', import.meta.url), 'utf8');

function extract(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  const b = src.indexOf(endMarker, a);
  assert.ok(a >= 0 && b > a, '未找到目标代码块：' + startMarker);
  return src.slice(a, b);
}

// 抽取三要点自测相关函数（到云同步块之前）
const tripleSrc = extract('/* ---- 三要点原文自测', '/* ---------- 可选云同步');
// 抽取模式切换/目录辅助（bindDrillModeSwitch 到 renderDrill 之前）
const helpersSrc = extract('function bindDrillModeSwitch()', 'function renderDrill()');

class Node {
  constructor(tag, cls = '', text = '') {
    this.tag = tag; this.className = cls; this.children = []; this._text = String(text);
    this.dataset = {}; this.classList = {
      toggle: (c, on) => { this.className = on ? (this.className + ' ' + c).trim() : this.className; },
    };
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text || this.children.map((c) => c.textContent).join(''); }
  set innerHTML(v) { this._text = ''; this.children = []; }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.children.push(c)); }
  querySelectorAll() { return []; }
  addEventListener(type, fn) { (this._ev ||= {})[type] = fn; }
  click() { this._ev?.click?.({ target: this }); }
}

function loadCtx(overrides = {}) {
  const nodes = {};
  const calls = [];
  const toasts = [];
  const ctx = vm.createContext({
    console, URL, Date, JSON, Math, Promise,
    $: (id) => nodes[id],
    el: (...a) => new Node(...a),
    toast: (m) => toasts.push(m),
    api: (path, body) => { calls.push([path, body]); return ctx.__res(path); },
    tripleCatalog: { books: {} },
    drillModeBound: false, drillData: { books: [] },
    drillBook: '系统解剖学', drillChapter: 1,
    tripleTask: null, tripleResult: null,
    tripleSelections: [null, null, null],
    tripleBusy: false, tripleDone: 0, tripleRight: 0,
    chapter: { no: 1, title: '运动系统', count: 202 },
    drillBookEntry: () => ({ chapters: [{ no: 1, title: '运动系统', count: 202 }] }),
    __res: () => ({}),
    ...overrides,
  });
  nodes.drillArea = new Node('div');
  nodes.drillKind = new Node('small');
  nodes.chapter = new Node('div');
  vm.runInContext(helpersSrc, ctx);
  vm.runInContext(tripleSrc, ctx);
  return { ctx, nodes, calls, toasts };
}

const makeTask = () => ({
  token: 'tok1', book: '系统解剖学', chapter: 1, kind: 'triple',
  prompt: '眼球外肌的神经支配',
  points: [{ label: '提上睑肌' }, { label: '上直肌' }, { label: '外直肌' }],
  options: [['动眼神经', '滑车神经'], ['动眼神经', '展神经'], ['展神经', '动眼神经']],
  notice: '自测不计入掌握度。',
});

test('模式切换 chip 只切换一次绑定，并清空另一种模式状态', () => {
  let captured = null;
  const switchBox = new Node('div');
  switchBox.addEventListener = (t, fn) => { captured = fn; };
  const { ctx } = loadCtx({
    drillMode: 'single', drillTask: { token: 'x' }, drillResult: { score: 90 },
    $: (id) => id === 'drillModeSwitch' ? switchBox : null,
    renderDrill: () => { ctx.__rendered = (ctx.__rendered || 0) + 1; },
  });
  ctx.bindDrillModeSwitch();
  ctx.bindDrillModeSwitch();
  assert.ok(captured, '应绑定点击事件');
  captured({ target: { closest: () => ({ dataset: { mode: 'triple' } }) } });
  assert.equal(ctx.drillMode, 'triple');
  assert.equal(ctx.drillTask, null);
  assert.equal(ctx.drillResult, null);
  assert.deepEqual([...ctx.tripleSelections], [null, null, null]);
  assert.equal(ctx.__rendered, 1);
});

test('三要点空状态引导开始，不误用单选端点', () => {
  const { ctx, nodes, calls } = loadCtx();
  ctx.renderTripleArea(ctx.chapter);
  assert.equal(calls.length, 0, '空状态不应发请求');
  const flat = JSON.stringify(nodes.drillArea.children.map((c) => c.textContent));
  assert.match(flat, /开始三要点自测/);
});

test('出题后逐要点渲染选项，选满才可提交', () => {
  const { ctx, nodes } = loadCtx({ tripleTask: makeTask() });
  ctx.renderTripleArea(ctx.chapter);
  const collect = (node, out = []) => {
    if (node.tag === 'button') out.push(node);
    (node.children || []).forEach((c) => collect(c, out));
    return out;
  };
  const flat = JSON.stringify(nodes.drillArea.children.map((c) => c.textContent));
  assert.match(flat, /要点 1：提上睑肌/);
  assert.match(flat, /要点 3：外直肌/);
  const buttons = collect(nodes.drillArea);
  const submit = buttons.find((b) => b.textContent === '提交自测');
  assert.ok(submit, '应有提交按钮');
  assert.equal(submit.disabled, true, '未选满时禁止提交');
  const dongyan = buttons.filter((b) => b.textContent === '动眼神经');
  assert.equal(dongyan.length, 3, '三个要点的选项里共出现三次动眼神经');
  dongyan[0]._ev.click();  // 第一个属于要点1
  assert.equal(ctx.tripleSelections[0], '动眼神经');
  assert.equal(ctx.tripleSelections[1], null, '只记录被点要点');
});

test('提交调用三要点判分端点，累计要点正确数并渲染结果', async () => {
  const res = {
    score: 67, correct: 2, chapter: 1,
    rubric: [
      { label: '提上睑肌', selected: '动眼神经', correct: true, expected: '动眼神经', reason: '' },
      { label: '上直肌', selected: '展神经', correct: false, expected: '动眼神经', reason: '同侧支配' },
      { label: '外直肌', selected: '展神经', correct: true, expected: '展神经', reason: '' },
    ],
    source: { term: '眼球外肌', explanation: '原文解释' },
    notice: '不计入掌握度',
  };
  const { ctx, nodes, calls } = loadCtx({
    tripleTask: makeTask(),
    tripleSelections: ['动眼神经', '展神经', '展神经'],
    __res: (path) => path === '/api/kaodian/triple-answer' ? res : {},
  });
  await ctx.answerTriple();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/api/kaodian/triple-answer');
  assert.deepEqual(calls[0][1].answers, ['动眼神经', '展神经', '展神经']);
  assert.equal(ctx.tripleDone, 1);
  assert.equal(ctx.tripleRight, 2);
  assert.match(nodes.drillKind.textContent, /要点对 2\/3/);
  // answerTriple 内部已渲染结果；显式再渲染一次验证结果与 chapter 传参无关。
  ctx.renderTripleArea(ctx.chapter);
  const flat = JSON.stringify(nodes.drillArea.children.map((c) => c.textContent));
  assert.match(flat, /自测 67 分/);
  assert.match(flat, /原文应为：动眼神经/);
  assert.match(flat, /不计入掌握度/);
});

test('结果页再来一道复用出题端点，不触碰掌握度接口', async () => {
  const { ctx, nodes, calls } = loadCtx({ tripleResult: {
    score: 100, correct: 3, chapter: 1, rubric: [], source: {}, notice: '不计入',
  } });
  ctx.renderTripleArea(ctx.chapter);
  const again = nodes.drillArea.children[0].children.find((c) => c.textContent === '再来一道');
  assert.ok(again, '结果页应有再来一道');
  ctx.__res = (path) => path === '/api/kaodian/triple-task' ? makeTask() : {};
  await again._ev.click();
  assert.deepEqual(calls.map((c) => c[0]), ['/api/kaodian/triple-task']);
  assert.ok(!calls.some((c) => c[0].includes('answer-text') || c[0].includes('/api/answer')));
});
