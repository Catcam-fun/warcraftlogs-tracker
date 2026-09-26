import { apiFetch, stripSecrets } from './api';
import { supabase } from './supabaseClient';

jest.mock('./supabaseClient', () => ({
  supabase: { auth: { getSession: jest.fn() } },
}));

const session = (s) => supabase.auth.getSession.mockResolvedValue({ data: { session: s } });

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ success: true }) });
});

test('stripSecrets removes WarcraftLogs credentials only', () => {
  const cfg = { guildName: 'G', clientId: 'id', clientSecret: 'secret', difficulty: '5' };
  expect(stripSecrets(cfg)).toEqual({ guildName: 'G', difficulty: '5' });
  expect(cfg.clientSecret).toBe('secret'); // original untouched
});

test('authenticated calls carry the session token', async () => {
  session({ access_token: 'tok' });
  await apiFetch('/api/saved', { auth: true });
  expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer tok');
});

test('authenticated calls fail fast without a session', async () => {
  session(null);
  const res = await apiFetch('/api/saved', { auth: true });
  expect(res.status).toBe(401);
  expect(global.fetch).not.toHaveBeenCalled();
});

test('optional auth still sends anonymous requests', async () => {
  session(null);
  const res = await apiFetch('/api/share', { method: 'POST', auth: 'optional', body: { a: 1 } });
  expect(res.ok).toBe(true);
  expect(global.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined();
});

test('network failures resolve with a readable error', async () => {
  global.fetch.mockRejectedValue(new TypeError('Failed to fetch'));
  const res = await apiFetch('/api/shared/abc');
  expect(res.ok).toBe(false);
  expect(res.body.error).toMatch(/server/i);
});
