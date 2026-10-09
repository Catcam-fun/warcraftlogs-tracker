"""Regenerate backend/max_health_auras.py from the game data on wago.tools.

How much each aura changes a player's maximum health, per game patch (the last
build of each patch since 11.0.2, as build_defensive_catalog.py uses), with the
talents and spec passives that change it. The death analysis needs it because
WarcraftLogs logs a killing hit after the death removed the player's auras: the
max health they had just before the blow is the max on their last hit before
it, with the auras that came up or ran out in between (each hit lists the auras
up on it) taken in or out.

An aura's size is a list of terms, each (1 + share) multiplied in, read from
where the game data puts the effect (Mythic rows when a spell has them):
  - the aura's own effects: EffectAura 133 (maximum health percent); 137 (total
    stat percent) with Stamina in its stat mask (EffectMiscValue_1 bit 4: 1
    Strength, 2 Agility, 4 Stamina, 8 Intellect); 80 (stat percent) on Stamina
    or all stats (EffectMiscValue_0 2 or -1); 34 / 230 (flat). Stamina percent
    counts as max health percent: a player's health is their Stamina times a
    constant (checked on logs, see the report);
  - another spell the aura's text names for its health ("Stamina increased by
    $1178s2%": Bear Form's passive 1178), under the text's condition when it has
    one ("$?a1250923[ Maximum health increased by $1250923s2%.]": Barkskin with
    the talent);
  - a talent whose own text says it raises the aura's maximum health ("Frenzied
    Regeneration also increases your maximum health by $s3%": Fount of Strength),
    same class;
  - the value a talent puts on the aura it triggers (EffectAura 231, proc with
    value: Ursine Vigor 377842 -> 393903);
  - CURATED: auras whose value lives in a description variable.
A term's base points can be changed by talents and spec passives (EffectAura
107 / 108 flat / percent, 219 / 220 by spell label) aimed at that effect: they
are kept as mods with who gets them (talent-tree entries, scaled by rank, or
spec names). Effects of one aura aimed at different units (ImplicitTarget_0)
land on different units: only the first such effect's target counts (Fortitude
of the Bear: +20% on you, +20% on your pet). Base points 0 that nothing above
explains: share None (not in the data), unless talents or spec passives aim at
that effect (EffectAura 107 / 108 / 219 / 220 on its index): then share 0.0 with
those mods, so the aura changes max health only with them (Bone Shield 195181
effect 2 with Foul Bulwark, +1% a charge; Ancestral Vigor 207400 with its talent
207401, +5%; Grimoire of Sacrifice 196099 with Profane Bargain, +3% Stamina).
Flat Stamina auras (EffectAura 29 on Stamina: Seabed Leviathan's Citrine) have
share None: health per Stamina point and item scaling are not in the data.
An aura that stacks (SpellAuraOptions.CumulativeAura, written to STACKING) has
its terms per stack: the analysis counts them once per stack, from the aura's
stack events.

    WAGO_CACHE=/tmp/wago python backend/scripts/build_max_health_auras.py
"""
import os
import pprint
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_defensive_catalog import patches, table  # noqa: E402

PERCENT, STAT_PERCENT, PERCENT_STAT, FLAT, FLAT_STAT = "133", "137", "80", ("34", "230"), "29"
STAMINA_BIT = 4
STAMINA_STATS = ("2", "-1")          # EffectAura 80 / 29 stat: 2 Stamina, -1 all stats (-2 is the primary stat)
PROC_WITH_VALUE = "231"
MOD_FLAT, MOD_PCT, MOD_FLAT_LABEL, MOD_PCT_LABEL = "107", "108", "219", "220"
MOD_OP_EFFECT_INDEX = {3: 0, 12: 1, 23: 2, 32: 3, 33: 4}   # SpellModOp "points of effect N"
PASSIVE = 0x40
MYTHIC = "16"
# Auras whose value is in a description variable: (aura, name, spell and effect index holding it,
# that spell's name). Checked against the names each build.
CURATED = [
    (97463, "Rallying Cry", 97462, 0, "Rallying Cry"),            # "$s1% temporary and maximum health" (in a raid)
    (120954, "Fortifying Brew", 115203, 0, "Fortifying Brew"),   # $health = $115203s1 (SpellDescriptionVariables 261)
]
# Auras with a max-health effect whose base points are 0 and that nothing fills in (no talent, text, proc
# or curated value): checked in the game data to change no max health. Moonkin Form's effect 3 (aura 133)
# is 0 and no talent or passive aims at it (11.0.7); its text names no health.
NO_HEALTH = {24858: "Moonkin Form"}
# How an aura's text says it raises max health or Stamina, right before the value it names: "Maximum
# health increased by", "Stamina increased by", "increasing (your) maximum health by". Only that phrasing:
# Healing Elixir's "heal for $428439s1% of your maximum health if brought below $122280s1% health" is a
# heal, not a max-health increase.
HEALTH_WORDS = (r"(?:(?:[Mm]aximum health|Stamina)(?: is)? increased by|"
                r"increas\w* (?:your )?(?:current and )?(?:maximum health|Stamina) by) ")


class Data:
    def __init__(self, build):
        self.names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName", build)}
        self.texts = {}
        for r in table("Spell", build):
            self.texts[int(r["ID"])] = ((r.get("AuraDescription_lang") or "") + " || " + (r["Description_lang"] or ""))
        self.effects = {}
        for r in table("SpellEffect", build):
            if r["DifficultyID"] not in ("0", MYTHIC):
                continue
            slot = self.effects.setdefault(int(r["SpellID"]), {})
            i = int(r["EffectIndex"])
            if i not in slot or r["DifficultyID"] == MYTHIC:
                slot[i] = r
        self.stacks = {int(r["SpellID"]): int(r["CumulativeAura"] or 0) for r in table("SpellAuraOptions", build)
                       if r["DifficultyID"] == "0" and int(r["CumulativeAura"] or 0) > 1}
        self.passive = {int(r["SpellID"]) for r in table("SpellMisc", build)
                        if r["DifficultyID"] == "0" and int(r["Attributes_0"]) & PASSIVE}
        self.family = {int(r["SpellID"]): (int(r["SpellClassSet"]), [int(r[f"SpellClassMask_{i}"]) & 0xffffffff
                                                                     for i in range(4)])
                       for r in table("SpellClassOptions", build)}
        self.labels = {}
        for r in table("SpellLabel", build):
            self.labels.setdefault(int(r["SpellID"]), set()).add(int(r["LabelID"]))
        entries_for_def = {}
        for r in table("TraitNodeEntry", build):
            entries_for_def.setdefault(int(r["TraitDefinitionID"]), set()).add(int(r["ID"]))
        self.talent_entries = {}
        for r in table("TraitDefinition", build):
            if int(r["SpellID"] or 0):
                self.talent_entries.setdefault(int(r["SpellID"]), set()).update(entries_for_def.get(int(r["ID"]), ()))
        specs = {r["ID"]: r["Name_lang"] for r in table("ChrSpecialization", build)}
        self.spec_spells = {}
        for r in table("SpecializationSpells", build):
            if r["SpecID"] in specs:
                self.spec_spells.setdefault(int(r["SpellID"]), set()).add(specs[r["SpecID"]])
        self.mod_rows = [r for effs in self.effects.values() for r in effs.values()
                         if r["Effect"] == "6" and r["EffectAura"] in (MOD_FLAT, MOD_PCT, MOD_FLAT_LABEL, MOD_PCT_LABEL)
                         and int(r["SpellID"]) in self.passive and float(r["EffectBasePointsF"] or 0)]

    def who(self, spell):
        """{"entries": [...]} (talent-tree entries), {"specs": [...]} (spec passive), or None (everyone
        who has the aura)."""
        if self.talent_entries.get(spell):
            return {"entries": sorted(self.talent_entries[spell])}
        if self.spec_spells.get(spell):
            return {"specs": sorted(self.spec_spells[spell])}
        return None

    def _covers(self, row, spell):
        if row["EffectAura"] in (MOD_FLAT_LABEL, MOD_PCT_LABEL):
            return int(row["EffectMiscValue_1"]) in self.labels.get(spell, ())
        fam, mask = self.family.get(spell, (None, [0] * 4))
        if fam is None or self.family.get(int(row["SpellID"]), (None,))[0] != fam:
            return False
        m = [int(row[f"EffectSpellClassMask_{i}"]) & 0xffffffff for i in range(4)]
        return any(a & b for a, b in zip(m, mask))

    def mods(self, spell, index):
        """Talents and spec passives that change one effect's base points: [{"add"|"mult", who}]."""
        out = []
        for r in self.mod_rows:
            if MOD_OP_EFFECT_INDEX.get(int(r["EffectMiscValue_0"])) != index or not self._covers(r, spell):
                continue
            who = self.who(int(r["SpellID"]))
            if who is None:
                continue                  # not a talent or spec passive: not something a loadout says
            value = float(r["EffectBasePointsF"])
            if r["EffectAura"] in (MOD_PCT, MOD_PCT_LABEL):
                out.append({"mult": round(1 + value / 100, 4), "by": int(r["SpellID"]), **who})
            else:
                out.append({"add": round(value / 100, 4), "by": int(r["SpellID"]), **who})
        return sorted(out, key=lambda m: m["by"])


def kind(r):
    """("pct" | "flat" | "stamina-points", base points) of a max-health effect, else None."""
    if r["Effect"] != "6":
        return None
    aura, v = r["EffectAura"], float(r["EffectBasePointsF"] or 0)
    if aura == PERCENT or (aura == STAT_PERCENT and int(r["EffectMiscValue_1"] or 0) & STAMINA_BIT) or \
            (aura == PERCENT_STAT and r["EffectMiscValue_0"] in STAMINA_STATS):
        return "pct", v
    if aura in FLAT:
        return "flat", v
    if aura == FLAT_STAT and r["EffectMiscValue_0"] in STAMINA_STATS:
        return "stamina-points", v
    return None


def build_terms(build, problems):
    d = Data(build)
    curated = {a: (n, s, i, sn) for a, n, s, i, sn in CURATED}
    # Talents whose text raises another aura's max health, by (class set, aura name).
    talent_refs = {}
    for t in d.talent_entries:
        m = re.search(r"([A-Z][\w' :-]+?) (?:also )?increases your maximum health by \$s(\d)%", d.texts.get(t, ""))
        if m and d.family.get(t):
            talent_refs.setdefault((d.family[t][0], m.group(1)), []).append((t, int(m.group(2)) - 1))
    # Values talents put on the auras they trigger.
    proc_values = {}
    for sid, effs in d.effects.items():
        for r in effs.values():
            if r["EffectAura"] == PROC_WITH_VALUE and int(r["EffectTriggerSpell"] or 0) and float(r["EffectBasePointsF"] or 0):
                proc_values.setdefault(int(r["EffectTriggerSpell"]), []).append((sid, int(r["EffectIndex"])))

    def term(spell, index, who=None):
        r = d.effects.get(spell, {}).get(index)
        if r is None:
            return None
        v = float(r["EffectBasePointsF"] or 0)
        out = {"from": spell, "index": index, "share": round(v / 100, 6) if v else None}
        if who:
            out.update(who)
        mods = d.mods(spell, index)
        if mods:
            out["mods"] = mods
        return out

    result = {}
    for sid, effs in d.effects.items():
        terms, seen, target, filled = [], set(), None, []
        own_unknown = False
        for i, r in sorted(effs.items()):
            k = kind(r)
            if k is None:
                continue
            target = r["ImplicitTarget_0"] if target is None else target
            if r["ImplicitTarget_0"] != target:
                continue
            if k[0] == "stamina-points":
                terms.append({"from": sid, "index": i, "share": None})
            elif k[0] == "flat" and k[1]:
                terms.append({"from": sid, "index": i, "flat": int(k[1])})
            elif k[1]:
                terms.append(term(sid, i))
            else:
                own_unknown = True        # computed: look below for where the value lives
                # A percent effect whose base points 0 talents fill (Foul Bulwark on Bone Shield). Not a flat
                # one: its value is computed (Fortifying Brew's health is a description variable, CURATED).
                mods = d.mods(sid, i) if k[0] == "pct" else None
                if mods:
                    filled.append({"from": sid, "index": i, "share": 0.0, "mods": mods})
            seen.add((sid, i))
        text = d.texts.get(sid, "")
        # Spells the aura's own text names for its health, with the text's condition.
        for m in re.finditer(r"(\$\?a(\d+)\[[^\]]*?)?" + HEALTH_WORDS + r"\$(\d+)s(\d)%", text):
            src, idx = int(m.group(3)), int(m.group(4)) - 1
            if (src, idx) in seen or idx not in d.effects.get(src, {}):
                continue
            cond = int(m.group(2)) if m.group(2) else None
            t = term(src, idx, d.who(cond) if cond else None)
            if t:
                terms.append(t)
                seen.add((src, idx))
        # The aura's own effect its text names for its health ("Maximum health increased by $s4%":
        # Vampiric Blood, whose max-health effect itself has base points 0).
        if own_unknown:
            for m in re.finditer(HEALTH_WORDS + r"\$[sw](\d)%", text):
                idx = int(m.group(1)) - 1
                if (sid, idx) not in seen and idx in effs and float(effs[idx]["EffectBasePointsF"] or 0):
                    terms.append(term(sid, idx))
                    seen.add((sid, idx))
                    own_unknown = False
        # Its own effect with base points 0 that talents or spec passives aim at: their value is the
        # size (none without them).
        if own_unknown and filled and sid not in curated:
            terms += filled
            own_unknown = False
        fam = d.family.get(sid, (None,))[0]
        # A talent already counted as a modifier of the aura's own effect is the same increase (Improved
        # Ardent Defender: "increases your maximum health by $s1%" is its +20% on Ardent Defender's effect 4).
        modded = {m["by"] for t in terms for m in t.get("mods", ())}
        for t_spell, idx in talent_refs.get((fam, d.names.get(sid)), ()) if fam else ():
            if (t_spell, idx) not in seen and t_spell not in modded:
                t = term(t_spell, idx, d.who(t_spell))
                if t:
                    terms.append(t)
                    seen.add((t_spell, idx))
        if own_unknown:
            found = False
            for src, idx in proc_values.get(sid, ()):
                t = term(src, idx, d.who(src))
                if t:
                    terms.append(t)
                    found = True
            if sid in curated:
                name, src, idx, src_name = curated[sid]
                if d.names.get(sid) != name or d.names.get(src) != src_name or idx not in d.effects.get(src, {}):
                    problems.append(f"curated {sid} {name}: now {d.names.get(sid)} / {d.names.get(src)}")
                else:
                    terms.append(term(src, idx))
                    found = True
            if not found and len(terms) == 0 and sid in NO_HEALTH:
                if d.names.get(sid) != NO_HEALTH[sid]:
                    problems.append(f"no-health {sid} {NO_HEALTH[sid]}: now {d.names.get(sid)}")
                continue
            if not found and len(terms) == 0:
                terms.append({"from": sid, "index": None, "share": None})
        if terms:
            result[sid] = sorted(terms, key=lambda t: (t["from"], t["index"] if t["index"] is not None else -1))
    # Auras that stack (SpellAuraOptions.CumulativeAura): each stack carries the effect, so the size is
    # per stack ("increasing your maximum health by $s11% ... per stack": Sentinel, 15 stacks).
    return result, {sid: d.stacks[sid] for sid in result if sid in d.stacks}


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "max_health_auras.py")
    history, stacking, problems = {}, {}, []
    for patch, first_day, build in patches():
        print(f"{patch} (build {build})...", flush=True)
        found, stacks = build_terms(build, problems)
        for aura in set(stacks) | set(stacking):
            h = stacking.setdefault(aura, [])
            n = stacks.get(aura, 1)
            if (not h and n > 1) or (h and h[-1][1] != n):
                h.append((patch, n))
        for aura, value in found.items():
            h = history.setdefault(aura, [])
            if not h or repr(h[-1][1]) != repr(value):
                h.append((patch, value))
        for aura, h in history.items():          # no longer changes max health in this patch
            if aura not in found and h[-1][1] != []:
                h.append((patch, []))
    if problems:
        raise SystemExit("game data changed; update CURATED:\n  " + "\n  ".join(sorted(set(problems))))
    with open(out, "w", newline="\n") as f:
        f.write('"""GENERATED by scripts/build_max_health_auras.py from wago.tools game data. Do not edit.\n\n'
                "How much each aura changes maximum health, by patch: {aura ID: [(first patch, terms), ...]}.\n"
                "Each term multiplies max health by (1 + share), or adds flat:\n"
                '  {"from": spell, "index": effect, "share": fraction or None (not in the data), "flat"?,\n'
                '   "entries"? (talent-tree entries: only with one of them), "specs"? (only those specs),\n'
                '   "mods"?: [{"add" (x rank) | "mult", "by": spell, "entries" | "specs"}]}.\n'
                'An empty list: the aura no longer changes max health in that patch."""\n\n')
        f.write("MAX_HEALTH = " + pprint.pformat(history, width=120, sort_dicts=True) + "\n\n")
        f.write("# Auras that stack, by patch: {aura ID: [(first patch, max stacks), ...]}. Their terms are per stack.\n")
        f.write("STACKING = " + pprint.pformat({a: h for a, h in stacking.items() if h}, width=120, sort_dicts=True)
                + "\n")
    print(f"Wrote {len(history)} auras to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
