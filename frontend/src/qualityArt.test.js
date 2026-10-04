import { qualityArt } from './DeathRow';

// Like every other piece of site art, the overlays live under PUBLIC_URL,
// so they still load when the site is served from a sub-path.
test('quality overlays are served from the site base path', () => {
  const before = process.env.PUBLIC_URL;
  process.env.PUBLIC_URL = '/floorpov';
  try {
    const rank = { rank: 2, ranks: [{ rank: 1 }, { rank: 2 }] };
    expect(qualityArt(rank)).toBe('/floorpov/art/quality/midnight-2.png');
  } finally {
    process.env.PUBLIC_URL = before;
  }
});
