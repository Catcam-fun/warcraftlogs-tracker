"""Measure each patch's potion factor from real boss-pull heals, for POTION_RANK_FACTOR
in build_defensive_catalog.py.

A health potion heals its rank's tooltip amount (the catalog's "ranks") times
(1 + the drinker's Versatility) times their healing-taken buffs and talents,
times a factor every potion of that patch shares (a server-side value the data
files don't carry; checked on live logs: players pile up exactly at factor x
silver and factor x gold, and it changes between patches). With Versatility
and buffs taken out of each heal, the factor is the one that puts the most
players exactly on a rank's tooltip.

When a potion's ranks are evenly spaced (The War Within: 4.3% apart), several
factors one step apart fit equally well. Such a patch is pinned down from the
next one instead: the same players drink the same rank across a patch change,
so the ratio of their heals on either side is the ratio of the two factors.

Cheap on the API: one request per report (heals of the boss pulls, with the
players' names), results cached on disk (POTION_CACHE, default
/tmp/potion_factor_cache) so a rerun never fetches twice, and the hourly rate
limit is checked as it goes: it waits for the reset instead of failing.

    WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... python backend/scripts/measure_potion_factor.py

Copy the printed table into POTION_RANK_FACTOR, then rebuild the catalog.
"""
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import defensives  # noqa: E402
from defensive_catalog import PATCHES  # noqa: E402
from warcraftlogs import GRAPHQL_ENDPOINT, get_access_token  # noqa: E402

# WarcraftLogs raid zone(s) live in each game version (Nerub-ar Palace,
# Liberation of Undermine, Manaforge Omega, Midnight Season 1, The Venomous
# Abyss). Add the new raid's zone for a new version.
ZONES = {"11.0": [38], "11.1": [42], "11.2": [44], "12.0": [46], "12.1": [53, 46]}
PLAYERS_PER_PATCH = 150        # enough players per potion to see the clusters
BOUNDARY_DAYS = 14             # reports this close to a patch change, for the cross-patch ratio
MATCH = 0.005                  # a player "on" a rank: within 0.5% of factor x its tooltip
AMBIGUOUS = 0.9                # another factor fitting this share as many players: not pinned down
MIN_PLAYERS = 10
CACHE = os.environ.get("POTION_CACHE", "/tmp/potion_factor_cache")
RATE_MARGIN = 0.9              # pause at this share of the hourly points


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class Api:
    """GraphQL with the hourly rate limit respected: waits instead of failing."""

    def __init__(self):
        self.token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
        self.calls = 0

    def _post(self, query, variables):
        while True:
            try:
                r = requests.post(GRAPHQL_ENDPOINT, json={"query": query, "variables": variables or {}},
                                  headers={"Authorization": f"Bearer {self.token}"}, timeout=120)
            except requests.RequestException as ex:
                log(f"network error ({str(ex)[:60]}), retrying in 30s")
                time.sleep(30)
                continue
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After") or 120)
                log(f"RATE LIMITED: waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 500:
                log(f"server error {r.status_code}, retrying in 30s")
                time.sleep(30)
                continue
            data = r.json()
            if data.get("errors"):
                raise RuntimeError(str(data["errors"])[:200])
            return data.get("data") or {}

    def __call__(self, query, variables=None):
        self.calls += 1
        if self.calls % 10 == 1:
            limit = self._post("{ rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }", None)
            limit = limit.get("rateLimitData") or {}
            spent, cap = limit.get("pointsSpentThisHour", 0), limit.get("limitPerHour") or 1
            log(f"rate limit: {spent:.0f} of {cap} points this hour, resets in {limit.get('pointsResetIn')}s")
            if spent >= cap * RATE_MARGIN:
                wait = int(limit.get("pointsResetIn") or 300) + 5
                log(f"PAUSING {wait}s for the hourly reset")
                time.sleep(wait)
        return self._post(query, variables)


def day_ms(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def report_codes(api, zone, start, end, page=1):
    data = api("""query($z: Int, $s: Float, $e: Float, $p: Int) { reportData {
        reports(zoneID: $z, startTime: $s, endTime: $e, limit: 25, page: $p) { data { code } has_more_pages } } }""",
               {"z": zone, "s": start, "e": end, "p": page})
    block = (data.get("reportData") or {}).get("reports") or {}
    return [r["code"] for r in block.get("data") or []], block.get("has_more_pages")


def report_heals(api, code, spell_ids):
    """One report's potion heals in boss pulls, per player: {(name, server): {spell: [heal events]}}. Cached."""
    path = os.path.join(CACHE, f"{code}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    out, start = {"start": None, "players": {}}, None
    flt = f"ability.id in ({', '.join(map(str, spell_ids))})"
    for _ in range(20):
        data = api("""query($c: String!, $f: String, $s: Float) { reportData { report(code: $c) {
            startTime masterData { actors(type: "Player") { id name server } }
            events(killType: Encounters, dataType: Healing, filterExpression: $f, includeResources: true,
                   startTime: $s, endTime: 1e13, limit: 10000) { data nextPageTimestamp } } } }""",
                   {"c": code, "f": flt, "s": start or 0})
        report = (data.get("reportData") or {}).get("report") or {}
        out["start"] = report.get("startTime")
        who = {a["id"]: f"{a['name']}-{a.get('server') or ''}" for a in (report.get("masterData") or {}).get("actors") or []}
        for e in (report.get("events") or {}).get("data") or []:
            if e.get("type") == "heal" and not e.get("tick") and e.get("sourceID") == e.get("targetID") \
                    and e.get("resourceActor") == 1 and e.get("targetID") in who:
                slim = {k: e.get(k) for k in ("abilityGameID", "amount", "overheal", "absorbed", "buffs", "versatility")}
                out["players"].setdefault(who[e["targetID"]], []).append(slim)
        start = (report.get("events") or {}).get("nextPageTimestamp")
        if not start:
            break
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def bases(heals, cat):
    """{spell: middle of this player's heals with Versatility and buffs taken out}."""
    per = defaultdict(list)
    for e in heals:
        full = (e.get("amount") or 0) + (e.get("overheal") or 0) + (e.get("absorbed") or 0)
        mult = defensives._heal_taken_mult(defensives._auras(e), cat)
        per[e["abilityGameID"]].append(full / mult / (1 + (e.get("versatility") or 0) / 10_000))
    return {sid: statistics.median(v) for sid, v in per.items()}


def fits(values, ranks):
    """Every factor that puts players on a rank's tooltip, with how many: [(factor, count)], best first."""
    found = {}
    for base in values:
        for heal in ranks:
            f = round(base / heal, 3)
            if f not in found:
                found[f] = sum(1 for b in values if min(abs(b / (f * r) - 1) for r in ranks) <= MATCH)
    # One entry per cluster of factors (within MATCH of each other), the best of each.
    best = []
    for f, n in sorted(found.items(), key=lambda x: -x[1]):
        if all(abs(f / g - 1) > MATCH for g, _ in best):
            best.append((f, n))
    return best


def refine(values, ranks, factor):
    on = [b / r for b in values for r in ranks if abs(b / (factor * r) - 1) <= MATCH]
    return round(statistics.median(on), 4) if on else factor


def main():
    api = Api()
    per_patch = {}       # patch -> {player: {spell: base}}
    for i, (first_day, patch) in enumerate(PATCHES):
        cat = defensives._CATALOGS[patch]
        potions = {sid: d for sid, d in cat.consumable.items() if d.get("ranks")}
        zones = ZONES.get(".".join(patch.split(".")[:2]))
        if not potions or not zones:
            continue
        start, end = day_ms(first_day), (day_ms(PATCHES[i + 1][0]) if i + 1 < len(PATCHES) else None)
        players = {}
        # Both ends of the patch window (for the cross-patch ratio), then the rest.
        windows = [(start, min(start + BOUNDARY_DAYS * 86_400_000, end or 9e15))]
        if end:
            windows.append((max(end - BOUNDARY_DAYS * 86_400_000, start), end))
        windows.append((start, end))
        for zone in zones:
            for n, (w_start, w_end) in enumerate(windows):
                goal = PLAYERS_PER_PATCH * (n + 1) // len(windows)
                page = 1
                while len(players) < goal:
                    codes, more = report_codes(api, zone, w_start, w_end, page)
                    for code in codes:
                        try:
                            r = report_heals(api, code, sorted(potions))
                        except RuntimeError as ex:        # private or deleted report
                            log(f"skip {code}: {str(ex)[:60]}")
                            continue
                        for name, heals in r["players"].items():
                            players.setdefault(name, {}).update(bases(heals, cat))
                        if len(players) >= goal:
                            break
                    log(f"{patch}: zone {zone}, window {n + 1}/{len(windows)}, page {page}: {len(players)} players")
                    if not more or not codes:
                        break
                    page += 1
        per_patch[patch] = players

    table, pinned = {}, {}
    for patch in [p for _, p in PATCHES if p in per_patch]:
        cat = defensives._CATALOGS[patch]
        for sid, d in cat.consumable.items():
            if not d.get("ranks"):
                continue
            values = [b[sid] for b in per_patch[patch].values() if sid in b]
            ranks = [r["heal"] for r in d["ranks"]]
            if len(values) < MIN_PLAYERS:
                log(f"{patch} {d['name']}: only {len(values)} players")
                continue
            options = fits(values, ranks)
            f, n = options[0]
            rivals = [g for g, m in options[1:] if m >= n * AMBIGUOUS]
            log(f"{patch} {d['name']}: best factor {f} ({n} of {len(values)} players on a rank)"
                + (f"; equally good: {rivals}" if rivals else ""))
            if not rivals:
                pinned[(patch, d["name"])] = refine(values, ranks, f)

    # Ambiguous patches: carried back from the next patch through the same players' heals.
    order = [p for _, p in PATCHES if p in per_patch]
    for idx in range(len(order) - 2, -1, -1):
        old, new = order[idx], order[idx + 1]
        for sid, d in defensives._CATALOGS[old].consumable.items():
            name = d["name"]
            if not d.get("ranks") or (old, name) in pinned:
                continue
            anchor = pinned.get((new, name))
            new_sid = next((s for s, e in defensives._CATALOGS[new].consumable.items() if e["name"] == name), None)
            if anchor is None or new_sid is None:
                continue
            ratios = [per_patch[old][p][sid] / per_patch[new][p][new_sid] for p in per_patch[old]
                      if sid in per_patch[old][p] and new_sid in per_patch[new].get(p, {})]
            if len(ratios) < MIN_PLAYERS:
                log(f"{old} {name}: only {len(ratios)} players in both {old} and {new}")
                continue
            # The most common ratio: players who kept their rank (a changed rank is one step off).
            ratio, n = max(((r, sum(1 for x in ratios if abs(x / r - 1) <= MATCH)) for r in ratios), key=lambda x: x[1])
            ratio = statistics.median([x for x in ratios if abs(x / ratio - 1) <= MATCH])
            pinned[(old, name)] = round(anchor * ratio, 4)
            log(f"{old} {name}: factor {pinned[(old, name)]} from {new} ({n} of {len(ratios)} players kept their rank)")

    for (patch, name), f in sorted(pinned.items(), key=lambda x: [int(v) for v in x[0][0].split(".")]):
        table.setdefault(name, []).append((patch, f))
    print("\nPOTION_RANK_FACTOR = {")
    for name, rows in table.items():
        print(f"    {name!r}: {rows},")
    print("}")


if __name__ == "__main__":
    main()
