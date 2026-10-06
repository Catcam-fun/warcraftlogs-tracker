import React from 'react';
import { render, screen } from '@testing-library/react';
import Settings from './Settings';
import PrivacyPolicy from './PrivacyPolicy';

// CRA's Jest resolver predates React Router 7's package exports.
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }), { virtual: true });
jest.mock('./supabaseClient', () => {
  const query = { select: () => query, eq: () => query, maybeSingle: async () => ({ data: null, error: null }) };
  return { supabase: { from: () => query } };
});

// The saved Client Secret is a plain column protected by row-level security
// and the database's encryption at rest; the copy must not promise more.
test('Settings describes how saved credentials are actually protected', () => {
  render(<Settings user={{ id: 'u1', email: 'a@b.c' }} onClose={jest.fn()} />);
  expect(screen.queryByText(/Encrypted and stored/i)).not.toBeInTheDocument();
  expect(screen.getByText(/no other account can read them/i)).toBeInTheDocument();
});

test('the Privacy Policy describes how saved credentials are actually protected', () => {
  render(<PrivacyPolicy user={null} />);
  expect(screen.queryByText(/these are encrypted at rest and used solely/i)).not.toBeInTheDocument();
  expect(screen.getByText(/no other account can read them/i)).toBeInTheDocument();
});

// Saves expire after the period chosen when saving (backend clamps to 30 days)
// and shares after 72 hours; the policy must not promise longer.
test('the Privacy Policy states how long saved analyses and shares are kept', () => {
  render(<PrivacyPolicy user={null} />);
  expect(screen.queryByText(/Analysis history: Retained until you delete your account/i)).not.toBeInTheDocument();
  expect(screen.getByText(/Saved analyses: kept for the period you choose when saving \(7, 14 or 30 days\)/i)).toBeInTheDocument();
  expect(screen.getByText(/Share links: expire 72 hours after they are created/i)).toBeInTheDocument();
});
