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


def wcl_players(run, rid, fid, roster):
    names = {norm(c["name"]) for c in run.summary(rid, fid)["composition"]}
    return names & roster if roster else names


def check(run):
    """Who was in each kept pull, and who counts as roster, match WCL"""
    if run.guild is None:
        return skip("no guild for this report")
    site = site_players(run.result)
    if not site:
        return skip("no pull participation")
    roster = get_guild_roster(run.token, *run.guild)
    items = []
    for key in sorted(site):
        rid, fid = key.rsplit("_", 1)
        wcl = wcl_players(run, rid, int(fid), roster)
        extra = sorted(site[key] - wcl)
        missing = sorted(wcl - site[key])
        if extra:
            items.append(f"pull {key}: site has {', '.join(extra)} that WCL lacks")
        if missing:
            items.append(f"pull {key}: WCL has {', '.join(missing)} that the site lacks")
    return fail(items) if items else PASS
