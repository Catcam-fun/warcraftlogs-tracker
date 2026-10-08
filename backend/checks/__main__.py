"""Command line: python -m checks <all|source|rules|check name|find-logs> <targets...> [--json PATH]"""
import json
import os
import sys

from checks.registry import rule_of, select
from checks.verdict import Verdict, exit_code, fail, format_lines, to_json


def run_checks(run, checks):
    """Run each check on `run`; an exception becomes a fail, never a crash."""
    verdicts = []
    for name, family, check in checks:
        try:
            outcome = check(run)
        except Exception as e:
            outcome = fail([], reason=f"{type(e).__name__}: {e}")
        verdicts.append(Verdict(name, family, rule_of(check), outcome))
    return verdicts


def main(argv):
    args = list(argv)
    json_path = None
    if "--json" in args:
        i = args.index("--json")
        json_path = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    what, targets = args[0], args[1:]

    if what == "find-logs":
        from checks import find_logs
        return find_logs.main(targets)

    try:
        checks = select(what)
    except ValueError as e:
        print(e)
        return 2
    if not targets:
        print(__doc__)
        return 2

    from checks.common import Run, parse_target, points
    from warcraftlogs import get_access_token

    token = get_access_token(os.environ["WCL_CLIENT_ID"], os.environ["WCL_CLIENT_SECRET"])
    all_verdicts, results = [], []
    for t in targets:
        run = Run(token, parse_target(t))
        before = points(token)
        verdicts = run_checks(run, checks)
        after = points(token)
        spent = after - before if before is not None and after is not None else None
        print(f"== {t}")
        print(format_lines(verdicts, spent), end="")
        all_verdicts.extend(verdicts)
        results.append({"target": t, **to_json(verdicts, spent)})
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"targets": results}, f, indent=2)
    return exit_code(all_verdicts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
