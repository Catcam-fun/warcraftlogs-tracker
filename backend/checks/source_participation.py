"""Source check: who was in each kept pull, against WarcraftLogs' own composition."""
from checks.verdict import PASS, fail, skip
from warcraftlogs import get_guild_roster, normalize_character_name


def norm(name):
    return normalize_character_name(name).lower()


def site_players(result):
    """Pull key -> {normalized player} from the site's pullParticipation."""
    out = {}
    for player, keys in (result.get("pullParticipation") or {}).items():
        for key in keys:
            out.setdefault(key, set()).add(norm(player))
    return out


def newest_names(run, rids):
    """{(report, actor ID): newest name} for renamed players: the same WoW ID and server under
    another name in a later report of the run (the owner's rename rule)."""
    actors, newest = [], {}
    for rid in rids:
        meta = run.meta_for(rid)
        for a in meta.get("friendlies") or []:
            who = (a.get("gameID"), a.get("server"))
            if all(who):
                actors.append((rid, a["id"], who))
                if meta.get("report_start", 0) >= newest.get(who, (-1, None))[0]:
                    newest[who] = (meta.get("report_start", 0), a["name"])
    return {(rid, aid): newest[who][1] for rid, aid, who in actors}


def wcl_players(run, rid, fid, roster, renamed=None):
    names = {norm((renamed or {}).get((rid, c.get("id"))) or c["name"])
             for c in run.summary(rid, fid)["composition"]}
    return names & roster if roster else names


def check(run):
    """Who was in each kept pull, and who counts as roster, match WCL (renamed players under their newest name)"""
    if run.guild is None:
        return skip("no guild for this report")
    site = site_players(run.result)
    if not site:
        return skip("no pull participation")
    roster = get_guild_roster(run.token, *run.guild)
    renamed = newest_names(run, sorted({key.rsplit("_", 1)[0] for key in site}))
    items = []
    for key in sorted(site):
        rid, fid = key.rsplit("_", 1)
        wcl = wcl_players(run, rid, int(fid), roster, renamed)
        extra = sorted(site[key] - wcl)
        missing = sorted(wcl - site[key])
        if extra:
            items.append(f"pull {key}: site has {', '.join(extra)} that WCL lacks")
        if missing:
            items.append(f"pull {key}: WCL has {', '.join(missing)} that the site lacks")
    return fail(items) if items else PASS
