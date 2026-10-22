import { apiFetch, bodyHash, stripSecrets, loadLocalCredentials, saveLocalCredentials } from './api';
import { supabase } from './supabaseClient';

jest.mock('./supabaseClient', () => ({
  supabase: { auth: { getSession: jest.fn() } },
}));

const session = (s) => supabase.auth.getSession.mockResolvedValue({ data: { session: s } });

// jsdom has no Web Crypto or TextEncoder; Node's are the same APIs the browser has.
const { webcrypto } = require('crypto');
const { TextEncoder } = require('util');
Object.defineProperty(window, 'crypto', { value: webcrypto, configurable: true });
window.TextEncoder = TextEncoder;

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ success: true }) });
});

test('stripSecrets removes WarcraftLogs credentials only', () => {
  const cfg = { guildName: 'G', clientId: 'id', clientSecret: 'secret', difficulty: '5' };
  expect(stripSecrets(cfg)).toEqual({ guildName: 'G', difficulty: '5' });
  expect(cfg.clientSecret).toBe('secret'); // original untouched
});

test('authenticated calls carry the session token outside Authorization', async () => {
  session({ access_token: 'tok' });
  await apiFetch('/api/saved', { auth: true });
  const { headers } = global.fetch.mock.calls[0][1];
  expect(headers['X-Session-Token']).toBe('tok');
  expect(headers.Authorization).toBeUndefined(); // CloudFront's signature goes there
});

test('bodies carry the SHA-256 Lambda needs behind CloudFront', async () => {
  // The standard SHA-256 test vector for "abc".
  expect(await bodyHash('abc')).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  session(null);
  await apiFetch('/api/share', { method: 'POST', auth: 'optional', body: { a: 1 } });
  const { headers, body } = global.fetch.mock.calls[0][1];
  expect(headers['x-amz-content-sha256']).toBe(await bodyHash(body));
  global.fetch.mockClear();
  await apiFetch('/api/shared/abc');
  expect(global.fetch.mock.calls[0][1].headers['x-amz-content-sha256']).toBeUndefined();
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
  expect(global.fetch.mock.calls[0][1].headers['X-Session-Token']).toBeUndefined();
});

test('network failures resolve with a readable error', async () => {
  global.fetch.mockRejectedValue(new TypeError('Failed to fetch'));
  const res = await apiFetch('/api/shared/abc');
  expect(res.ok).toBe(false);
  expect(res.body.error).toMatch(/server/i);
});

test('credentials are remembered in this browser and cleared when emptied', () => {
  localStorage.clear();
  expect(loadLocalCredentials()).toEqual({ clientId: '', clientSecret: '' });
  saveLocalCredentials('id', 'secret');
  expect(loadLocalCredentials()).toEqual({ clientId: 'id', clientSecret: 'secret' });
  saveLocalCredentials('', '');
  expect(localStorage.length).toBe(0);
});

test('unreadable stored credentials start the form empty', () => {
  localStorage.setItem('fpx.wclCredentials', '{broken');
  expect(loadLocalCredentials()).toEqual({ clientId: '', clientSecret: '' });
  localStorage.clear();
});
