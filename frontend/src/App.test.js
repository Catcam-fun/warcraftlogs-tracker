import fs from 'fs';
import path from 'path';

const readSrc = (file) => fs.readFileSync(path.join(__dirname, file), 'utf8');

test('visual shell renders across user-facing surfaces', () => {
  expect(readSrc('index.css')).toContain('--color-bg');
  expect(readSrc('index.css')).toContain('--class-warrior');
  expect(readSrc('index.css')).toContain('.surface-panel');
  expect(readSrc('LandingPage.js')).toContain('landing-shell');
  expect(readSrc('Auth.js')).toContain('auth-shell');
  expect(readSrc('App.js')).toContain('analysis-shell');
  expect(readSrc('App.js')).toContain('ResponsiveContainer');
  expect(readSrc('SharedResults.js')).toContain('shared-results-shell');
  expect(readSrc('SharedResults.js')).toContain('ResponsiveContainer');
  expect(readSrc('Settings.js')).toContain('settings-shell');
  expect(readSrc('TermsOfService.js')).toContain('legal-shell');
  expect(readSrc('PrivacyPolicy.js')).toContain('legal-shell');
});
