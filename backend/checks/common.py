"""Shared pieces of the checks: targets, the lazy Run with cached WCL fetchers, points, the in-process analysis."""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import analysis
import app
import defensives
from warcraftlogs import (get_access_token, get_fights, get_report_fights, get_guild_reports,  # noqa: F401
                          get_guild_roster, graphql_query, normalize_character_name)

TABLE_CAP = 200
LETHAL_WINDOW_MS = 15000


@dataclass
class Target:
    code: str
    raid: str
    guild: tuple = None   # (name, server, region)


class TableCapped(Exception):
    """A Deaths table hit WCL's 200-entry cap; args: (rid, fid)."""


class AnalysisError(Exception):
    """The site's own analysis returned an error; args: (error text,)."""


def parse_target(s):
    parts = s.split(":", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise SystemExit(f"Bad target {s!r}; use <reportCode>:<raidKey>[:<Guild>/<Server>/<REGION>]")
    code, raid = parts[0], parts[1]
    if raid not in analysis.RAID_ENCOUNTERS:
        raise SystemExit(f"Unknown raid key {raid}; one of: {', '.join(analysis.RAID_ENCOUNTERS)}")
    guild = None
    if len(parts) == 3 and parts[2]:
        g = parts[2].split("/")
        if len(g) != 3:
            raise SystemExit(f"Bad guild {parts[2]!r}; use <Guild>/<Server>/<REGION>")
        guild = (g[0], g[1], g[2])
    return Target(code, raid, guild)


def raid_week(start_ms):
    """The raid week holding start_ms: the Tuesday (UTC) on or before it, and that Tuesday + 7 days."""
    d = datetime.fromtimestamp(start_ms / 1000, timezone.utc).date()
    tuesday = d - timedelta(days=(d.weekday() - 1) % 7)
    return tuesday.isoformat(), (tuesday + timedelta(days=7)).isoformat()


def points(token):
    try:
        data = graphql_query(token, "query { rateLimitData { pointsSpentThisHour } }")
        return data["rateLimitData"]["pointsSpentThisHour"]
    except Exception:
        return None


def run_analysis(token_unused, target, start, end):
    """Post to /api/analyze in process and return the final result."""
    name, server, region = target.guild
    body = {
        "clientId": os.environ["WCL_CLIENT_ID"], "clientSecret": os.environ["WCL_CLIENT_SECRET"],
        "guildName": name, "server": server, "region": region,
        "fightZone": 0, "selectedRaid": target.raid, "difficulty": 5, "maxCutoff": 10,
        "rosterOnly": True, "enableCheatDeath": False, "startDate": start, "endDate": end,
    }
    raw = app.app.test_client().post("/api/analyze", json=body).get_data(as_text=True)
    result = None
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith("data:"):
            continue
        payload = json.loads(chunk[len("data:"):].strip())
        if "error" in payload:
            raise AnalysisError(payload["error"])
        if "result" in payload:
            result = payload["result"]
    if result is None:
        raise AnalysisError(f"no result from /api/analyze: {raw[:200]}")
    return result


def _report(data):
    return (data.get("reportData") or {}).get("report") or {}


class Run:
    """One target's shared state. Nothing is fetched until a property or method needs it."""

    def __init__(self, token, target):
        self.token = token
        self.target = target
        self.code = target.code
        self.raid = target.raid
        self._cache = {}

    def _memo(self, key, make):
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def _q(self, query, variables):
        return graphql_query(self.token, query, variables)

    @property
    def meta(self):
        return self.meta_for(self.code)

    def meta_for(self, rid):
        return self._memo(("meta", rid), lambda: get_fights(self.token, rid))

    @property
    def pulls(self):
        return self._memo(("pulls",), lambda: analysis.analyze_fights(self.meta["fights"], None, 5, self.raid))

    @property
    def cat(self):
        return self._memo(("cat",), lambda: defensives.catalog_for(self.meta["report_start"]))

    @property
    def guild(self):
        def make():
            if self.target.guild:
                return self.target.guild
            q = ("query($c: String!) { reportData { report(code: $c) "
                 "{ guild { name server { name region { slug } } } } } }")
            g = _report(self._q(q, {"c": self.code})).get("guild")
            if not g:
                return None
            return (g["name"], g["server"]["name"], g["server"]["region"]["slug"].upper())
        return self._memo(("guild",), make)

    @property
    def result(self):
        def make():
            if self.guild is None:
                raise AnalysisError("no guild for this report; pass code:raid:Guild/Server/REGION")
            start, end = raid_week(self.meta["report_start"])
            return run_analysis(self.token, Target(self.code, self.raid, self.guild), start, end)
        return self._memo(("result",), make)

    def actor_id(self, rid, name):
        want = normalize_character_name(name).lower()
        for a in self.meta_for(rid).get("friendlies", []):
            if normalize_character_name(a["name"]).lower() == want:
                return a["id"]
        return None

    def fight(self, rid, fid):
        for f in self.meta_for(rid)["fights"]:
            if f["id"] == fid:
                return f
        raise KeyError(f"fight {fid} not in report {rid}")

    def _table(self, rid, fid, data_type, pid=None):
        decl = "$c: String!, $f: [Int]" + (", $p: Int" if pid is not None else "")
        extra = ", targetID: $p" if pid is not None else ""
        q = (f"query({decl}) {{ reportData {{ report(code: $c) {{ "
             f"t: table(dataType: {data_type}, fightIDs: $f{extra}) }} }} }}")
        variables = {"c": rid, "f": [fid]}
        if pid is not None:
            variables["p"] = pid
        return (_report(self._q(q, variables)).get("t") or {}).get("data") or {}

    def deaths_table(self, rid, fid):
        def make():
            entries = self._table(rid, fid, "Deaths").get("entries") or []
            if len(entries) >= TABLE_CAP:
                raise TableCapped(rid, fid)
            return entries
        return self._memo(("deaths", rid, fid), make)

    def summary(self, rid, fid):
        return self._memo(("summary", rid, fid), lambda: self._table(rid, fid, "Summary"))

    def buffs(self, rid, fid, pid):
        return self._memo(("buffs", rid, fid, pid),
                          lambda: self._table(rid, fid, "Buffs", pid).get("auras") or [])

    def _events(self, rid, data_type, who, pid, start, end, fight_ids=None):
        events, cursor = [], start
        for _ in range(50):
            decl = "$c: String!, $p: Int, $s: Float, $e: Float" + (", $f: [Int]" if fight_ids else "")
            fargs = ", fightIDs: $f" if fight_ids else ""
            q = (f"query({decl}) {{ reportData {{ report(code: $c) {{ events(dataType: {data_type}, "
                 f"{who}: $p, startTime: $s, endTime: $e{fargs}, limit: 10000) "
                 f"{{ data nextPageTimestamp }} }} }} }}")
            variables = {"c": rid, "p": pid, "s": cursor, "e": end}
            if fight_ids:
                variables["f"] = fight_ids
            block = _report(self._q(q, variables)).get("events") or {}
            events += block.get("data") or []
            cursor = block.get("nextPageTimestamp")
            if not cursor:
                break
        return events

    def casts(self, rid, pid, start, end):
        return self._memo(("casts", rid, pid, start, end),
                          lambda: self._events(rid, "Casts", "sourceID", pid, start, end))

    def hits_before(self, rid, fid, pid, death_ts):
        return self._memo(("hits", rid, fid, pid, death_ts), lambda: self._events(
            rid, "DamageTaken", "targetID", pid, death_ts - LETHAL_WINDOW_MS, death_ts + 50, fight_ids=[fid]))

    def combatants(self, rid, fid):
        def make():
            f = self.fight(rid, fid)
            return defensives.fetch_combatants(self.token, rid, [fid], f["start_time"], f["end_time"])
        return self._memo(("combatants", rid, fid), make)

    def counted_deaths(self):
        """Every counted death: within the cutoff, not in a wipe, not a cheat death."""
        r = self.result
        cutoff = r["meta"]["maxCutoff"]
        out = []
        for value in r["events"].values():
            for e in (value if isinstance(value, list) else [value]):
                if e.get("slot") is not None and e["slot"] <= cutoff \
                        and not e.get("inWipe") and not e.get("isCheatDeath"):
                    out.append(e)
        return out
