import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
// Import as ESM without changing the repository's package type.
const code = await readFile(new URL('./worker.js', import.meta.url), 'utf8');
const { dispatch, default: worker } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const time = Date.parse('2026-10-22T00:07:00Z');
const env = { GH_ACTIONS_TOKEN: 'test-private-value' };

function fake(statuses) {
  const logs = [], requests = [], waits = [];
  return { logs, requests, waits, io: {
    log: r => logs.push(r), sleep: async ms => waits.push(ms),
    fetch: async (url, options) => {
      requests.push({ url, options });
      const status = statuses.shift();
      if (status === 'network') throw new Error(env.GH_ACTIONS_TOKEN);
      return new Response(status === 204 ? null : 'secret-containing-response', { status });
    },
  }};
}

test('204 dispatch uses the existing workflow with live queries and source label', async () => {
  const f = fake([204]); await dispatch(env, time, f.io);
  assert.match(f.requests[0].url, /altay-fare-watch.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(f.requests[0].options.body), {
    ref: 'main', inputs: { dry_run: 'false', trigger_source: 'cloudflare' },
  });
  assert.equal(f.logs[0].event, 'dispatch_accepted');
  assert.equal(f.logs[0].scheduled_at, '2026-10-22T00:07:00.000Z');
  assert.ok(!JSON.stringify(f.logs).includes(env.GH_ACTIONS_TOKEN));
});

test('missing secret never contacts GitHub', async () => {
  const f = fake([]); await assert.rejects(dispatch({}, time, f.io), /not configured/);
  assert.equal(f.requests.length, 0);
});

test('transient errors retry and recover without logging credentials', async () => {
  const f = fake(['network', 503, 204]); await dispatch(env, time, f.io);
  assert.equal(f.requests.length, 3); assert.deepEqual(f.waits, [1000, 2000]);
  assert.ok(!JSON.stringify(f.logs).includes(env.GH_ACTIONS_TOKEN));
});

test('permanent auth errors are not retried', async () => {
  const f = fake([401]); await assert.rejects(dispatch(env, time, f.io), /HTTP 401/);
  assert.equal(f.requests.length, 1);
});

test('rate-limit retries are bounded', async () => {
  const f = fake([429, 429, 429]); await assert.rejects(dispatch(env, time, f.io), /HTTP 429/);
  assert.equal(f.requests.length, 3);
});

test('network failure retries are bounded and safe', async () => {
  const f = fake(['network', 'network', 'network']);
  await assert.rejects(dispatch(env, time, f.io), /network failure after 3 attempts/);
  assert.equal(f.requests.length, 3);
});

test('monitor end date stops dispatch at Beijing midnight', async () => {
  const f = fake([]); await dispatch(env, Date.parse('2026-12-24T00:00:00+08:00'), f.io);
  assert.equal(f.requests.length, 0); assert.equal(f.logs[0].event, 'dispatch_inactive');
});

test('public HTTP cannot trigger the workflow', async () => {
  assert.equal((await worker.fetch(new Request('https://example.com'))).status, 404);
});

test('Cron runtime waits for dispatch completion', async () => {
  const original = globalThis.fetch; globalThis.fetch = async () => new Response(null, { status: 204 });
  const pending = [];
  try {
    await worker.scheduled({ scheduledTime: time }, env, { waitUntil: p => pending.push(p) });
    await Promise.all(pending); assert.equal(pending.length, 1);
  } finally { globalThis.fetch = original; }
});
