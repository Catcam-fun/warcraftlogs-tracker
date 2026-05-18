/* Dev-only fixture for iterating on the /results redesign without a live
   WarcraftLogs run. Shape mirrors what the backend returns and what
   getFilteredStats / getOverviewData / getAnalysisChartData consume:

     events[player]            -> [{ boss, reportId, fightId, isCheatDeath,
                                      timestamp, absTs, pullNo, abilityName,
                                      class, spec, defensives }]
     pullParticipation[player] -> [pullKey...]            (pullKey = `${reportId}_${fightId}`)
     bossParticipation[boss]   -> { [player]: [pullKey...] }
     pullCutoffTimestamps[key] -> { 1: ms, 2: ms, ... }   (Nth raid death cutoff)
     meta                      -> { maxCutoff }

   Injected only when ?mock=1 is present AND not a production build
   (see App.js). Never imported by the real data path. */

const MAX_CUTOFF = 5;

const BOSSES = [
  'Plexus Sentinel',
  "Loom'ithar",
  'Soulbinder Naazindhri',
  'Forgeweaver Araz',
  'The Soul Hunters',
  'Fractillus',
  'Nexus-King Salhadaar',
  'Dimensius, the All-Devouring',
];

// progression curve — farm bosses few pulls / low deaths, last two bosses
// are the prog wall. [pulls, deathChance]
const BOSS_PROFILE = {
  'Plexus Sentinel': [10, 0.18],
  "Loom'ithar": [12, 0.22],
  'Soulbinder Naazindhri': [14, 0.26],
  'Forgeweaver Araz': [18, 0.32],
  'The Soul Hunters': [22, 0.4],
  'Fractillus': [26, 0.46],
  'Nexus-King Salhadaar': [48, 0.6],
  'Dimensius, the All-Devouring': [72, 0.72],
};

const BOSS_ABILITIES = {
  'Plexus Sentinel': ['Eradicating Salvo', 'Powered Automaton', 'Obliteration Arcanocannon', 'Manifest Matrix'],
  "Loom'ithar": ['Lair Weaving', 'Arcane Outrage', "Loom'ithar's Bite", 'Piercing Strand'],
  'Soulbinder Naazindhri': ['Soul Calling', 'Arcane Expulsion', 'Mystic Lash', 'Soulfray Annihilation'],
  'Forgeweaver Araz': ['Silencing Tempest', 'Arcane Obliteration', 'Overwhelming Power', 'Invoke Collector'],
  'The Soul Hunters': ['Felblade', "Eye Beam", 'The Hunt', 'Collective Felscar'],
  'Fractillus': ['Shattering Backhand', 'Crystalline Shockwave', 'Void Rifts', 'Reverberating Fracture'],
  'Nexus-King Salhadaar': ['Banishment', 'Nexus Beams', "King's Hour", 'Conquer', 'Vanquish', 'Galactic Smash'],
  'Dimensius, the All-Devouring': ['Devour', 'Mass Suppression', 'Reckless Devastation', 'Black Hole', 'Dark Matter', 'Singularity'],
};

const DEFENSIVES_BY_CLASS = {
  Warrior: ['Shield Wall', 'Die by the Sword', 'Rallying Cry'],
  Paladin: ['Divine Shield', 'Blessing of Sacrifice', 'Ardent Defender'],
  Hunter: ['Aspect of the Turtle', 'Survival of the Fittest'],
  Rogue: ['Cloak of Shadows', 'Evasion', 'Feint'],
  Priest: ['Pain Suppression', 'Desperate Prayer', 'Dispersion'],
  DeathKnight: ['Anti-Magic Shell', 'Icebound Fortitude', 'Vampiric Blood'],
  Shaman: ['Astral Shift', 'Earth Elemental'],
  Mage: ['Ice Block', 'Greater Invisibility', 'Alter Time'],
  Warlock: ['Unending Resolve', 'Dark Pact'],
  Monk: ['Fortifying Brew', 'Touch of Karma', 'Diffuse Magic'],
  Druid: ['Survival Instincts', 'Barkskin', 'Renewal'],
  DemonHunter: ['Blur', 'Netherwalk', 'Darkness'],
  Evoker: ['Obsidian Scales', 'Renewing Blaze', 'Zephyr'],
};

// 22-person mythic roster, realistic class/spec spread + a couple of alts
const ROSTER = [
  { player: 'Vandelis', class: 'DeathKnight', spec: 'Blood' },
  { player: 'Breuly', class: 'Warrior', spec: 'Protection' },
  { player: 'Sastrugi', class: 'Druid', spec: 'Restoration' },
  { player: 'Mendokai', class: 'Priest', spec: 'Holy' },
  { player: 'Tolwerin', class: 'Paladin', spec: 'Holy' },
  { player: 'Quinvala', class: 'Shaman', spec: 'Restoration' },
  { player: 'Drannoch', class: 'Evoker', spec: 'Preservation' },
  { player: 'Faylinn', class: 'Mage', spec: 'Frost' },
  { player: 'Korrathil', class: 'Warlock', spec: 'Destruction' },
  { player: 'Sylphara', class: 'Hunter', spec: 'Marksmanship' },
  { player: 'Razgore', class: 'DemonHunter', spec: 'Havoc' },
  { player: 'Nimuewen', class: 'Druid', spec: 'Balance' },
  { player: 'Threnody', class: 'Rogue', spec: 'Assassination' },
  { player: 'Vexmoira', class: 'Mage', spec: 'Arcane' },
  { player: 'Holdrane', class: 'Paladin', spec: 'Retribution' },
  { player: 'Brackwyn', class: 'Monk', spec: 'Windwalker' },
  { player: 'Eltherios', class: 'Evoker', spec: 'Devastation' },
  { player: 'Pyrrhosa', class: 'Warlock', spec: 'Affliction' },
  { player: 'Caldwynn', class: 'Hunter', spec: 'Beast Mastery' },
  { player: 'Mossfen', class: 'Druid', spec: 'Feral' },
  { player: 'Vandalt', class: 'DeathKnight', spec: 'Frost' },   // alt of Vandelis
  { player: 'Brewly', class: 'Monk', spec: 'Brewmaster' },       // alt of Brackwyn
];

const REPORTS = ['aB1cD2eF3gH4jK5m', 'nP6qR7sT8uV9wX0y', 'zA1bC2dE3fG4hJ5k', 'lM6nO7pQ8rS9tU0v'];

// small deterministic PRNG so the fixture is stable across reloads
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function build() {
  const rand = mulberry32(0x10A3);
  const events = {};
  const pullParticipation = {};
  const bossParticipation = {};
  const pullCutoffTimestamps = {};

  ROSTER.forEach((r) => { events[r.player] = []; pullParticipation[r.player] = []; });
  BOSSES.forEach((b) => { bossParticipation[b] = {}; });

  const tierStart = Date.parse('2026-04-28T20:00:00');
  let absClock = tierStart;
  let fightCounter = {};
  REPORTS.forEach((rid) => { fightCounter[rid] = 1; });

  BOSSES.forEach((boss, bossIdx) => {
    const [pulls, deathChance] = BOSS_PROFILE[boss];
    const abilities = BOSS_ABILITIES[boss];

    for (let p = 0; p < pulls; p++) {
      const reportId = REPORTS[Math.min(REPORTS.length - 1, Math.floor((p / pulls) * REPORTS.length))];
      const fightId = fightCounter[reportId]++;
      const pullKey = `${reportId}_${fightId}`;
      const pullNo = p + 1;
      // later pulls in prog last a bit longer
      const pullLenMs = 90000 + Math.floor(rand() * 240000) + bossIdx * 12000;
      absClock += 6 * 60 * 1000 + Math.floor(rand() * 4 * 60 * 1000);
      const pullAbsStart = absClock;

      // who is in this pull (a couple of alts swap in occasionally)
      const present = ROSTER.filter((r) => {
        if (r.player === 'Vandalt') return rand() < 0.12;
        if (r.player === 'Brewly') return rand() < 0.12;
        return true;
      });
      present.forEach((r) => {
        bossParticipation[boss][r.player] = bossParticipation[boss][r.player] || [];
        bossParticipation[boss][r.player].push(pullKey);
        pullParticipation[r.player].push(pullKey);
      });

      // raid death sequence for this pull (real + occasional cheat)
      const deaths = [];
      present.forEach((r) => {
        if (rand() < deathChance) {
          const ts = 8000 + Math.floor(rand() * (pullLenMs - 8000));
          const cheat = rand() < 0.1;
          deaths.push({
            player: r.player,
            ts,
            isCheatDeath: cheat,
            abilityName: rand() < 0.06 ? 'Unknown' : abilities[Math.floor(rand() * abilities.length)],
            class: r.class,
            spec: r.spec,
          });
        }
      });
      deaths.sort((a, b) => a.ts - b.ts);

      // cutoff N = timestamp of the Nth real (non-cheat) raid death
      const cuts = {};
      let realSeen = 0;
      for (const d of deaths) {
        if (d.isCheatDeath) continue;
        realSeen += 1;
        if (realSeen <= MAX_CUTOFF) cuts[realSeen] = d.ts;
        if (realSeen >= MAX_CUTOFF) break;
      }
      if (realSeen === 0) cuts[1] = Math.floor(pullLenMs * 0.5);
      pullCutoffTimestamps[pullKey] = cuts;

      deaths.forEach((d) => {
        const defs = DEFENSIVES_BY_CLASS[d.class] || [];
        const active = defs.filter(() => rand() < 0.4).map((name) => ({ name, count: 1 + Math.floor(rand() * 2) }));
        events[d.player].push({
          boss,
          reportId,
          fightId,
          isCheatDeath: d.isCheatDeath,
          timestamp: d.ts,
          absTs: pullAbsStart + d.ts,
          pullNo,
          abilityName: d.abilityName,
          class: d.class,
          spec: d.spec,
          defensives: { abilities: active, healing: Math.floor(rand() * 850000) },
        });
      });
    }
  });

  return {
    events,
    pullParticipation,
    bossParticipation,
    pullCutoffTimestamps,
    meta: { maxCutoff: MAX_CUTOFF },
  };
}

export const MOCK_RESULTS = build();

export const MOCK_CONFIG = {
  clientId: 'mock', clientSecret: 'mock',
  guildName: 'Floor Pov', server: 'Area 52',
  region: 'us', selectedRaid: 'manaforge',
  reportZone: '44', fightZone: '2810',
  difficulty: '5', maxCutoff: '5',
  startDate: '', endDate: '', authorFilters: '', characterGroups: '',
  enableCheatDeath: true, enableDefensiveTracking: true,
};
