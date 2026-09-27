"""Regenerate backend/boss_spell_text.py from the live game data on wago.tools.

The in-game description of every boss spell in the raids in
analysis.RAID_ENCOUNTERS (the Dungeon Journal's spells, the spells they
trigger, and the spells whose description points at one of those), by spell
ID, for the killing-blow tooltip on the results page.

Blizzard's description templates are filled in from the game data where the
data is exact: durations ($d), tick intervals ($t), radii ($a / $A), spell
names and linked descriptions, and percentages. Damage amounts are left out
("inflicts Shadow damage"): the game scales them at runtime by difficulty
and item level, so the stored numbers would be wrong. The tooltip shows the
real hit from the log instead. Difficulty and class conditions ($?DIFF16[...],
$?a12345[...]) are dropped. Rerun when a new raid or patch comes out (after
adding the raid to RAID_ENCOUNTERS):

    python backend/scripts/build_boss_spell_text.py

Needs network access to wago.tools.
"""
import os
import pprint
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import RAID_ENCOUNTERS  # noqa: E402
from build_defensive_catalog import patches, table  # noqa: E402

MAX_DEPTH = 4


class Data:
    def __init__(self, build):
        self.names = {int(r["ID"]): r["Name_lang"] for r in table("SpellName", build)}
        self.desc = {int(r["ID"]): r["Description_lang"] for r in table("Spell", build) if r["Description_lang"]}
        durations = {int(r["ID"]): int(r["Duration"]) for r in table("SpellDuration", build)}
        radii = {int(r["ID"]): float(r["Radius"]) for r in table("SpellRadius", build)}
        self.duration = {}
        for r in table("SpellMisc", build):
            if r["DifficultyID"] == "0" and durations.get(int(r["DurationIndex"] or 0), 0) > 0:
                self.duration[int(r["SpellID"])] = durations[int(r["DurationIndex"])]
        self.effects = {}
        for r in table("SpellEffect", build):
            if r["DifficultyID"] == "0":
                self.effects.setdefault(int(r["SpellID"]), {})[int(r["EffectIndex"]) + 1] = {
                    "points": float(r["EffectBasePointsF"] or 0),
                    "period": int(r["EffectAuraPeriod"] or 0),
                    "radius": radii.get(int(r["EffectRadiusIndex_0"] or 0)) or radii.get(int(r["EffectRadiusIndex_1"] or 0)),
                    "trigger": int(r["EffectTriggerSpell"] or 0),
                }


def _num(x):
    return f"{x:g}"


def _secs(ms):
    s = ms / 1000
    return f"{_num(s / 60)} min" if s >= 60 and s % 60 == 0 else f"{_num(round(s, 1))} sec"


def render(data, sid, depth=0):
    """A spell's description with its template filled in (None if nothing readable is left)."""
    text = data.desc.get(sid)
    if not text or depth > MAX_DEPTH:
        return None

    def effect(ref, idx):
        return data.effects.get(int(ref) if ref else sid, {}).get(int(idx), {})

    # Links: |cFF2959D3|Hspell:123|h[Name]|h|r -> Name; other colour codes -> their text.
    text = re.sub(r"\|c[0-9A-Fa-f]{8}\|H[^|]*\|h\[([^\]]*)\]\|h\|r", r"\1", text)
    text = re.sub(r"\|c[0-9A-Fa-f]{8}(.*?)\|r", r"\1", text, flags=re.S)
    # Conditions: $?DIFF16[...][...], $?a123[...][...], $?s123[...], $[!16 ...] -> dropped.
    for _ in range(3):
        text = re.sub(r"\$\?[^\[\]]*\[[^\[\]]*\](\[[^\[\]]*\])?", "", text)
        text = re.sub(r"\$\[[^\[\]]*\]", "", text)
    text = re.sub(r"\$@spelldesc(\d+)", lambda m: render(data, int(m.group(1)), depth + 1) or "", text)
    text = re.sub(r"\$@spellname(\d+)", lambda m: data.names.get(int(m.group(1)), ""), text)
    text = re.sub(r"\$@\w+?\d*", "", text)
    text = text.replace("$bullet;", "•").replace("$bullet", "•")
    text = re.sub(r"\$[gG]([^:;]*):[^;]*;", r"\1", text)                       # $ghis:her; -> his
    text = re.sub(r"\$(\d*)d\b", lambda m: _secs(data.duration.get(int(m.group(1)) if m.group(1) else sid, 0))
                  if data.duration.get(int(m.group(1)) if m.group(1) else sid) else "", text)
    text = re.sub(r"\$(\d*)t(\d)", lambda m: _num(effect(m.group(1), m.group(2)).get("period", 0) / 1000)
                  if effect(m.group(1), m.group(2)).get("period") else "", text)
    text = re.sub(r"\$(\d*)[aA](\d)", lambda m: _num(effect(m.group(1), m.group(2)).get("radius") or 0)
                  if effect(m.group(1), m.group(2)).get("radius") else "", text)
    # Percentages are exact; damage and healing amounts scale at runtime, so they go.
    text = re.sub(r"\$(\d*)[sSmMwW](\d)(?=\s*(%|sec|min|yard|yd|stack|target|time|charge))",
                  lambda m: _num(abs(effect(m.group(1), m.group(2)).get("points", 0)))
                  if effect(m.group(1), m.group(2)).get("points") else "", text)
    text = re.sub(r"\$\{[^}]*\}", "", text)
    text = re.sub(r"\$\d*[a-zA-Z]+\d*", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\bwithin (yards|yds)\b", "nearby", text)
    text = re.sub(r"\bevery (sec|seconds?)\b", "periodically", text)
    text = re.sub(r"\b(for|by|of)\s*(?=[.,;]|$)", "", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text).replace("( ", "(").replace(" )", ")").replace("()", "").strip()
    return text if len(text) > 12 else None


def main():
    build = patches()[-1][2]
    data = Data(build)
    encounters = set().union(*RAID_ENCOUNTERS.values())
    journal = {int(r["ID"]) for r in table("JournalEncounter", build) if int(r["DungeonEncounterID"]) in encounters}
    seen, stack = set(), [int(r["SpellID"]) for r in table("JournalEncounterSection", build)
                          if int(r["JournalEncounterID"]) in journal and r["SpellID"] != "0"]
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        seen.add(sid)
        stack += [e["trigger"] for e in data.effects.get(sid, {}).values() if e["trigger"]]
    # Damage spells often only point at the journal spell's description, or the
    # journal spell points at theirs (Sever): follow those links both ways.
    points_to = {sid: int(m.group(1)) for sid, text in data.desc.items()
                 if (m := re.fullmatch(r"\$@spelldesc(\d+)", text.strip()))}
    grew = True
    while grew:
        grew = False
        for sid, target in points_to.items():
            for a, b in ((sid, target), (target, sid)):
                if a in seen and b not in seen:
                    seen.add(b)
                    grew = True
    out = {}
    for sid in sorted(seen):
        text = render(data, sid)
        if text:
            out[sid] = text
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "boss_spell_text.py")
    texts = sorted(set(out.values()))
    index = {t: i for i, t in enumerate(texts)}
    with open(path, "w") as f:
        f.write('"""GENERATED by scripts/build_boss_spell_text.py from wago.tools game data.\n'
                'In-game description of each raid boss spell (damage amounts left out).\n'
                'Use text_for(spell ID)."""\n\n')
        f.write("TEXTS = " + pprint.pformat(texts, width=110) + "\n\n")
        f.write("# spell ID -> index in TEXTS\n")
        f.write("SPELLS = " + pprint.pformat({sid: index[t] for sid, t in out.items()}, width=110, compact=True) + "\n\n\n")
        f.write("def text_for(spell_id):\n    i = SPELLS.get(spell_id)\n    return None if i is None else TEXTS[i]\n")
    print(f"Wrote {len(out)} descriptions to {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
