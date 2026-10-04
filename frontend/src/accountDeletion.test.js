import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import Settings from './Settings';
import { apiFetch, saveLocalCredentials, loadLocalCredentials } from './api';
import { supabase } from './supabaseClient';

jest.mock('./supabaseClient', () => {
  const query = { select: () => query, eq: () => query, maybeSingle: async () => ({ data: null, error: null }) };
  return { supabase: { from: () => query, auth: { signOut: jest.fn(async () => ({})) } } };
});
jest.mock('./api', () => {
  const actual = jest.requireActual('./api');
  return { ...actual, apiFetch: jest.fn() };
});

test('deleting the account also forgets the WarcraftLogs key saved in this browser', async () => {
  apiFetch.mockResolvedValue({ ok: true, status: 200, body: { success: true } });
  supabase.auth.signOut.mockResolvedValue({});
  saveLocalCredentials('id-123', 'secret-456');
  const assign = jest.fn();
  delete window.location;
  window.location = { assign };
  render(<Settings user={{ id: 'u1', email: 'a@b.c' }} onClose={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /delete my account/i }));
  fireEvent.change(screen.getByPlaceholderText(/Type DELETE to confirm/), { target: { value: 'DELETE' } });
  fireEvent.click(screen.getByRole('button', { name: /confirm delete/i }));
  expect(await screen.findByText(/Account deleted successfully/i)).toBeInTheDocument();
  expect(loadLocalCredentials()).toEqual({ clientId: '', clientSecret: '' });
});
