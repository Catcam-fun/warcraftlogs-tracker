// Encounter IDs and boss names:
// https://github.com/BigWigsMods/BigWigs/tree/master/TheVenomousAbyss
// https://github.com/BigWigsMods/BigWigs/tree/master/MidnightLairs
// reportZone is intentionally unset: the backend fetches reports by date,
// then filters fights from both instances by the season's encounter IDs.
export const SEASON_TWO_RAIDS = [
  {
    key: 'midnight-s2-all',
    name: 'Midnight Season 2',
    exp: 'MIDNIGHT',
    reportZone: null,
    fightZone: '0', // Combined tier: Venomous Abyss (3004) and Tidebound Grotto (2987).
    emblem: 'venom',
    bosses: [
      "Nek'zali the Soulcoiler",
      'Entombed Sentinels',
      'The Lost Explorers',
      'Vashnik the Malignant',
      'Sszorak',
      'The Twin Fangs',
      'The Coiled Altar',
      "Ula'tek",
      'Nymrissa Wavecaller',
    ],
  },
];
