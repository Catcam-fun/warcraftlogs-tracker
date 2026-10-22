import { friendlyError, CONNECTION } from './friendlyError';

test('network failures read as a connection problem', () => {
  expect(friendlyError(new TypeError('Failed to fetch'), 'fallback')).toBe(CONNECTION);
  expect(friendlyError(new Error('NetworkError when attempting to fetch resource.'), 'fallback')).toBe(CONNECTION);
});

test('messages naming addresses or services are replaced by the fallback', () => {
  const leaky = new Error('Request failed for url: https://upstream.example.test/oauth/token');
  expect(friendlyError(leaky, 'Please try again.')).toBe('Please try again.');
  expect(friendlyError(new Error('AuthApiError from Supabase'), 'Please try again.')).toBe('Please try again.');
  expect(friendlyError(undefined, 'Please try again.')).toBe('Please try again.');
});

test('messages written for people pass through', () => {
  expect(friendlyError(new Error('Invalid login credentials'), 'x')).toBe('Invalid login credentials');
  expect(friendlyError(new Error('Invalid JSON format for character groups'), 'x'))
    .toBe('Invalid JSON format for character groups');
});
