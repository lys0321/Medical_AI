import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const cfgSrc = readFileSync(new URL('../web/cloud-config.js', import.meta.url), 'utf8');
const cloudSrc = readFileSync(new URL('../web/cloud.js', import.meta.url), 'utf8');

function loadCloud({ withSdk = true } = {}) {
  const window = {};
  const fakeClient = {
    auth: { getSession: async () => ({ data: { session: null } }) },
    database: { from() { throw new Error('database must not be touched while signed out'); } },
    llm: { models: { list: async () => [] } }
  };
  if (withSdk) window.WorkBuddyCloud = { createWorkBuddyCloud: () => fakeClient };
  const ctx = vm.createContext({ window, console, URL, Date, JSON, Math,
    location: { href: 'http://localhost:7860/', pathname: '/', search: '', hash: '' },
    history: { replaceState() {} } });
  vm.runInContext(cfgSrc, ctx);
  vm.runInContext(cloudSrc, ctx);
  return { ctx, C: window.MedNexusCloud };
}

test('cloud config exposes only public client config, never a secret', () => {
  const { ctx } = loadCloud();
  const c = ctx.window.MEDNEXUS_CLOUD;
  assert.match(c.endpoint, /^https:\/\//);
  assert.match(c.publishableKey, /^wbpk_/);
  assert.equal(c.secret, undefined);
  assert.equal(c.apiKey, undefined);
});

test('sanitize keeps only allowlisted summary keys', () => {
  const { C } = loadCloud();
  const report = {
    course: '系统解剖学', concepts: [{ id: 'a', name: '动眼神经', mastered: true }],
    stats: { attempts: 5 }, recommendation: { id: 'x' }, errors: {}, time: {}, method: 'm',
    history: [{ concept: 'a', result: { rubric: [] } }], events: [{ kind: 'private' }],
    evidence_report: { secret: 1 }
  };
  const out = C.sanitize(report);
  assert.equal(out.course, '系统解剖学');
  assert.deepEqual(Object.keys(out).sort(),
    ['concepts', 'course', 'errors', 'excluded', 'method', 'recommendation', 'schema_version', 'stats', 'synced_at', 'time'].sort());
  assert.equal(out.history, undefined);
  assert.equal(out.events, undefined);
  assert.equal(out.evidence_report, undefined);
});

test('sanitize strips answer text and identity from every concept', () => {
  const { C } = loadCloud();
  const out = C.sanitize({ concepts: [{
    id: 'a', name: 'A', unit: '脑神经', mastered: true, score: 0.9,
    answer_text: 'PRIVATE_ANSWER', question: 'PRIVATE_Q', learner: 'SECRET_ID', token: 'SECRET'
  }] });
  assert.equal(out.concepts[0].id, 'a');
  assert.equal(out.concepts[0].mastered, true);
  assert.equal(out.concepts[0].answer_text, undefined);
  assert.equal(out.concepts[0].question, undefined);
  assert.equal(out.concepts[0].learner, undefined);
  assert.equal(out.concepts[0].token, undefined);
  assert.equal(JSON.stringify(out).includes('PRIVATE'), false);
  assert.equal(JSON.stringify(out).includes('SECRET'), false);
});

test('sanitize declares exclusions and is deterministic in shape', () => {
  const { C } = loadCloud();
  const out = C.sanitize({ stats: {}, concepts: [] });
  assert.ok(Array.isArray(out.excluded) && out.excluded.length >= 4);
  assert.equal(out.schema_version, 1);
  assert.equal(typeof out.synced_at, 'number');
  assert.equal(C.sanitize(null), null);
});

test('upload/download require sign-in before touching the database', async () => {
  const { C } = loadCloud();
  // SDK present but no session: init() succeeds, session is null.
  const up = await C.upload({ stats: {}, concepts: [] });
  assert.equal(up.ok, false);
  assert.match(up.error, /登录/);
  const down = await C.download();
  assert.equal(down.ok, false);
  assert.match(down.error, /登录/);
});

test('OAuth callback reads session from the SDK data envelope', async () => {
  // SDK returns { data: session, error } on WorkBuddy/WeChat callbacks.
  const window = {};
  const session = { user: { name: '测试同学' } };
  let handlerCalled = false;
  const fakeClient = {
    auth: {
      handleWorkBuddyCallback: async () => { handlerCalled = true; return { data: session, error: null }; },
      getSession: async () => ({ data: { session: null } })
    },
    database: { from() { throw new Error('should not touch db'); } },
    llm: { models: { list: async () => [] } }
  };
  window.WorkBuddyCloud = { createWorkBuddyCloud: () => fakeClient };
  const ctx = vm.createContext({ window, console, URL, Date, JSON, Math,
    location: { href: 'http://localhost:7860/?code=abc&state=s&provider=workbuddy', pathname: '/', search: '?code=abc&state=s&provider=workbuddy', hash: '' },
    history: { replaceState() {} } });
  // location.search must expose searchParams through URL parsing in cloud.js.
  ctx.location.href = 'http://localhost:7860/?code=abc&state=s&provider=workbuddy';
  vm.runInContext(cfgSrc, ctx);
  vm.runInContext(cloudSrc, ctx);
  const result = await ctx.window.MedNexusCloud.handleCallback();
  assert.equal(handlerCalled, true);
  assert.equal(result.signedIn, true);
  assert.equal(result.user.name, '测试同学');
  assert.deepEqual(ctx.window.MedNexusCloud.currentUser(), session.user);
});
