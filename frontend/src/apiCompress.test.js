import { gunzipSync } from 'zlib';
import { CompressionStream as NodeCompressionStream } from 'stream/web';
import { TextEncoder as NodeTextEncoder } from 'util';
import { apiFetch } from './api';

jest.mock('./supabaseClient', () => ({ supabase: { auth: { getSession: jest.fn() } } }));

// Lambda refuses request bodies over 6 MB; big analyses are gzipped first.
beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ success: true }) });
});
afterEach(() => { delete global.CompressionStream; });

test('compress: true sends gzip that decodes to the same JSON', async () => {
  global.CompressionStream = NodeCompressionStream;
  global.TextEncoder = global.TextEncoder || NodeTextEncoder;
  const body = { data: { events: { Bob: [1, 2, 3] } }, config: { guildName: 'G' } };
  await apiFetch('/api/share', { method: 'POST', body, compress: true });
  const [, init] = global.fetch.mock.calls[0];
  expect(init.headers['Content-Encoding']).toBe('gzip');
  expect(init.headers['Content-Type']).toBe('application/json');
  expect(JSON.parse(gunzipSync(Buffer.from(init.body)).toString())).toEqual(body);
});

test('browsers without CompressionStream send plain JSON', async () => {
  await apiFetch('/api/share', { method: 'POST', body: { a: 1 }, compress: true });
  const [, init] = global.fetch.mock.calls[0];
  expect(init.headers['Content-Encoding']).toBeUndefined();
  expect(JSON.parse(init.body)).toEqual({ a: 1 });
});
