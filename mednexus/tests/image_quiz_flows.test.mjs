import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../web/image-quiz.js', import.meta.url), 'utf8');

class Node {
  constructor(tag = 'div', cls = '', text = '') {
    this.tag = tag; this.className = cls || ''; this._text = text ?? '';
    this.children = []; this.listeners = {}; this.disabled = false; this.hidden = false;
  }
  set textContent(value) { this._text = value ?? ''; this.children = []; }
  get textContent() { return this._text; }
  append(...items) { items.forEach(item => this.children.push(item)); }
  appendChild(item) { this.children.push(item); return item; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
}

const all = node => [node, ...node.children.flatMap(all)];
const text = node => all(node).map(item => item.textContent).join(' ');

const QUESTION = {
  token: 't'.repeat(32), kind: 'image', image_number: 2,
  image_url: '/api/course-materials/images/histology-2.png',
  prompt: '第 2 页资料的小标题是下面哪一项？',
  options: ['被覆上皮的类型', '红细胞形态', '白细胞分类', '血小板结构'],
  review_status: 'pending', notice: '标注待教师审核：由 OCR 机械抽取，未经医学教师核对。',
};

const STATS = {attempts: 3, correct: 2, accuracy: 0.667};

function setup(answers = {}) {
  const calls = [];
  const container = new Node();
  const context = vm.createContext({
    el: (tag, cls, text) => new Node(tag, cls, text),
    api: async (path, body) => {
      calls.push([path, body]);
      if (body.action === 'next') return answers.next ?? {available: true, question: QUESTION, stats: STATS};
      return answers.answer ?? {correct: true, answer: QUESTION.options[0], result: {tissue: '结缔组织', stains: ['HE染色']}, stats: {attempts: 4, correct: 3, accuracy: 0.75}};
    },
    imageQuizBusy: false,
  });
  vm.runInContext(source, context);
  return {context, container, calls, mount: () => context.mountImageQuiz(container)};
}

const chips = container => all(container).filter(node => node.className === 'chip');

test('识图练习自动出题，题目与图片都带“待教师审核”标注', async () => {
  const s = setup();
  await s.mount();
  assert.equal(s.calls[0][0], '/api/image-quiz');
  assert.equal(s.calls[0][1].action, 'next');
  assert.match(text(s.container), /待教师审核/);
  const image = all(s.container).find(node => node.tag === 'img');
  assert.equal(image.src, QUESTION.image_url);
  assert.match(image.alt, /待教师审核/);
  assert.equal(chips(s.container).length, 4);
  assert.match(text(s.container), /第 2 页资料的小标题/);
});

test('点击选项提交答案并显示正确小标题与单独统计', async () => {
  const s = setup();
  await s.mount();
  const target = chips(s.container)[0];
  target.listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  const answerCall = s.calls.at(-1);
  assert.equal(answerCall[1].action, 'answer');
  assert.equal(answerCall[1].token, QUESTION.token);
  assert.equal(answerCall[1].choice, target.textContent);
  assert.match(text(s.container), /答对了/);
  assert.match(text(s.container), /单独统计，不计入三要点/);
  assert.match(text(s.container), /该页自动标注（待教师审核）/);
});

test('答错时给出正确答案而不是只报错', async () => {
  const s = setup({answer: {correct: false, answer: '被覆上皮的类型', result: {}, stats: STATS}});
  await s.mount();
  chips(s.container)[1].listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(text(s.container), /答错了，正确的小标题是：被覆上皮的类型/);
});

test('没有标注时说明原因，不出题也不渲染选项', async () => {
  const s = setup({next: {available: false, reason: 'no_labels', message: '本机还没有组胚识图标注', stats: null}});
  await s.mount();
  assert.match(text(s.container), /本机还没有组胚识图标注/);
  assert.equal(chips(s.container).length, 0);
  assert.equal(all(s.container).find(node => node.tag === 'img'), undefined);
});