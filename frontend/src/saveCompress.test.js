import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SaveReportDialog from './SaveReportDialog';
import { apiFetch } from './api';

jest.mock('./supabaseClient', () => ({ supabase: { auth: { getSession: jest.fn() } } }));
jest.mock('./api', () => ({ ...jest.requireActual('./api'), apiFetch: jest.fn() }));

// A saved analysis can be bigger than the 6 MB Lambda accepts, so it's gzipped.
test('saving sends the analysis compressed', async () => {
  apiFetch.mockResolvedValue({ ok: true, status: 201, body: { success: true } });
  const onSaved = jest.fn();
  render(<SaveReportDialog analysisData={{ meta: {}, events: {} }} config={{ guildName: 'G' }}
    onClose={jest.fn()} onSaved={onSaved} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Raid night' } });
  fireEvent.click(screen.getByRole('button', { name: /save/i }));
  await screen.findByRole('button', { name: /save/i });
  expect(apiFetch).toHaveBeenCalledWith('/api/saved', expect.objectContaining({ method: 'POST', compress: true }));
});
