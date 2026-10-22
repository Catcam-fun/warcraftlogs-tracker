// node --test infra/breaker/handler.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { render, TEMPLATE, HANDLER } from './build.mjs';

const { makeHandler } = createRequire(import.meta.url)('./handler.js');

// Fake AWS clients that record every call.
function fakes({ enabled = true, failApi = false } = {}) {
  const calls = [];
  const config = { Enabled: enabled, Comment: 'Floor Pov', Origins: { Quantity: 2 } };
  const cf = {
    getDistributionConfig: async (input) => {
      calls.push(['getDistributionConfig', input]);
      return { DistributionConfig: structuredClone(config), ETag: 'E1' };
    },
    updateDistribution: async (input) => { calls.push(['updateDistribution', input]); },
  };
  const lambda = {
    putFunctionConcurrency: async (input) => {
      calls.push(['putFunctionConcurrency', input]);
      if (failApi) throw new Error('throttled');
    },
  };
  const logs = [];
  const handler = makeHandler({ cf, lambda, distId: 'DIST', apiFunction: 'api-fn', log: (m) => logs.push(m) });
  return { handler, calls, logs };
}

const sns = (...messages) => ({ Records: messages.map((Message) => ({ Sns: { Message } })) });
const alarm = (state) => JSON.stringify({ AlarmName: 'floorpov-breaker-requests', NewStateValue: state });

test('an alarm going back to OK is ignored', async () => {
  const { handler, calls } = fakes();
  assert.deepEqual(await handler(sns(alarm('OK'))), { tripped: false });
  assert.deepEqual(calls, []);
});

test('an alarm stops the API and disables CloudFront with the same config', async () => {
  const { handler, calls } = fakes();
  assert.deepEqual(await handler(sns(alarm('ALARM'))), { tripped: true });
  assert.deepEqual(calls[0], ['putFunctionConcurrency', { FunctionName: 'api-fn', ReservedConcurrentExecutions: 0 }]);
  assert.deepEqual(calls[1], ['getDistributionConfig', { Id: 'DIST' }]);
  assert.deepEqual(calls[2], ['updateDistribution', {
    Id: 'DIST', IfMatch: 'E1',
    DistributionConfig: { Enabled: false, Comment: 'Floor Pov', Origins: { Quantity: 2 } },
  }]);
});

test('a budget message (plain text) trips', async () => {
  const { handler, calls } = fakes();
  await handler(sns('AWS Budget Notification: actual cost is greater than $10.00'));
  assert.deepEqual(calls.map((c) => c[0]), ['putFunctionConcurrency', 'getDistributionConfig', 'updateDistribution']);
});

test('an already-disabled distribution is left alone', async () => {
  const { handler, calls, logs } = fakes({ enabled: false });
  await handler(sns(alarm('ALARM')));
  assert.deepEqual(calls.map((c) => c[0]), ['putFunctionConcurrency', 'getDistributionConfig']);
  assert.ok(logs.some((l) => /already disabled/.test(l)));
});

test('one failed step still runs the other, then fails so the delivery is retried', async () => {
  const { handler, calls } = fakes({ failApi: true });
  await assert.rejects(handler(sns(alarm('ALARM'))), /throttled/);
  assert.ok(calls.some((c) => c[0] === 'updateDistribution'));
});

test('breaker.yaml carries the current handler.js', () => {
  const template = readFileSync(TEMPLATE, 'utf8').replace(/\r\n/g, '\n');
  assert.equal(render(template, readFileSync(HANDLER, 'utf8')), template,
    'run node infra/breaker/build.mjs');
});
