import fs from 'fs';
import path from 'path';
import React from 'react';
import { render } from '@testing-library/react';
import FpMark from './FpMark';

const PUBLIC = path.join(__dirname, '..', 'public');

// Like every other piece of site art, the mark lives under PUBLIC_URL. It has
// a copy per common screen scaling: a 125%-scaled Windows screen given only
// 1x/2x stretches the 32px copy to 40px and blurs it.
test('the FP mark loads from the site base path at every common scaling', () => {
  const before = process.env.PUBLIC_URL;
  process.env.PUBLIC_URL = '/floorpov';
  try {
    const { container } = render(<FpMark />);
    const img = container.querySelector('img');
    expect(img.getAttribute('src')).toBe('/floorpov/fp-mark-32.png');
    expect(img.getAttribute('srcset')).toBe(
      '/floorpov/fp-mark-40.png 1.25x, /floorpov/fp-mark-48.png 1.5x, '
      + '/floorpov/fp-mark-64.png 2x, /floorpov/fp-mark-96.png 3x');
    for (const f of ['fp-mark-32.png', 'fp-mark-40.png', 'fp-mark-48.png', 'fp-mark-64.png', 'fp-mark-96.png']) {
      expect(fs.existsSync(path.join(PUBLIC, f))).toBe(true);
    }
  } finally {
    process.env.PUBLIC_URL = before;
  }
});

// A missing icon fails silently in the browser (the tab or home-screen icon
// just falls back), so check every one the page and manifest point to.
test('every icon index.html and manifest.json reference exists', () => {
  const html = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8');
  const fromHtml = [...html.matchAll(/<link rel="(?:icon|apple-touch-icon)"[^>]*href="%PUBLIC_URL%\/([^"]+)"/g)]
    .map((m) => m[1]);
  const manifest = JSON.parse(fs.readFileSync(path.join(PUBLIC, 'manifest.json'), 'utf8'));
  const files = [...fromHtml, ...manifest.icons.map((i) => i.src)];
  expect(fromHtml).toEqual(expect.arrayContaining(['favicon.ico', 'favicon-32.png', 'apple-touch-icon.png']));
  for (const f of files) {
    expect([f, fs.existsSync(path.join(PUBLIC, f))]).toEqual([f, true]);
  }
});
