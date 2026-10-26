// Encounter IDs and boss names:
// https://github.com/BigWigsMods/BigWigs/tree/master/TheVenomousAbyss
// https://github.com/BigWigsMods/BigWigs/tree/master/MidnightLairs
// https://github.com/BigWigsMods/BigWigs/tree/master/TheUnbindingOfKithix
// reportZone is intentionally unset: the backend fetches reports by date,
// then filters fights from both instances by the season's encounter IDs.
export const SEASON_TWO_RAIDS = [
  {
    key: 'midnight-s2-all',
    name: 'Midnight Season 2',
    exp: 'MIDNIGHT',
    reportZone: null,
    fightZone: '0', // Combined tier: Venomous Abyss (3004), Tidebound Grotto (2987) and The Unbinding of Kith'ix (3095).
    final: "Ula'tek", // raid card art on the Analyze page
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
      "Kith'ix",
    ],
  },
];
