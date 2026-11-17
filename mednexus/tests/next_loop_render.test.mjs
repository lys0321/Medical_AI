import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../web/learning-report.js', import.meta.url), 'utf8');
const segment = () => source.slice(source.indexOf('function renderNextLoop'), source.indexOf('function mountLearningReport'));

function harness() {
  const nodes = [];
  const node = (tag, cls, text) => ({ tag, cls, text, children: [],
    append(...n) { this.children.push(...n); }, appendChild(n) { this.children.push(n); } });
  const ctx = vm.createContext({ el: (tag, cls, text) => node(tag, cls, text), Date });
  vm.runInContext(segment(), ctx);
  return { ctx, node };
}

const loop = {
  diagnoses: [{ category: '概念混淆', remediation: '按原文逐一对照。' }],
  next_activity: {
    misconception: '概念混淆', concept_name: '动眼神经', remediation: '按原文逐一对照。',
    rejection: undefined,
    retest_points: [{ label: '提上睑肌', category: '概念记忆', correct: '上睑提肌', reason: '由动眼神经支配' }],
    due_at: 1700000000, timing_basis: '按 srs 到期',
    variation: { angle: '与另一要点辨识' }
  }
};

test('renders a G5 remediation card from orchestration output', () => {
  const { ctx } = harness();
  const card = ctx.renderNextLoop(loop);
  assert.ok(card);
  const text = JSON.stringify(card);
  assert.match(text, /下一步/);
  assert.match(text, /概念混淆/);
  assert.match(text, /提上睑肌/);
  assert.match(text, /重测/);
});

test('never renders mastery claims and skips empty loop', () => {
  const { ctx } = harness();
  assert.equal(ctx.renderNextLoop(null), null);
  assert.equal(ctx.renderNextLoop({}), null);
  const card = ctx.renderNextLoop(loop);
  // The UI must not declare any concept "mastered"; the only near-match is the
  // boundary disclaimer "不判定已掌握", which is a negation and is allowed.
  const claimLines = card.children.filter(n => /已掌握/.test(n.text || '') && !/不判定/.test(n.text || ''));
  assert.equal(claimLines.length, 0);
});

test('handles a loop with activity but no diagnosis', () => {
  const { ctx } = harness();
  const card = ctx.renderNextLoop({ next_activity: { misconception: 'unknown', due_at: null } });
  assert.ok(card);
  assert.match(JSON.stringify(card), /尽快/);
});
