import { shareNote } from './shareNote';

test('a link kept only in server memory says it may stop working', () => {
  expect(shareNote({ success: true, ephemeral: true })).toMatch(/stop working when the server restarts/i);
});

test('a normal link has no warning', () => {
  expect(shareNote({ success: true, ephemeral: false })).toBeNull();
  expect(shareNote({ success: true })).toBeNull();
});
