import unittest
from unittest import mock

import warcraftlogs
from analysis import RAID_DATE_WINDOWS, RAID_ENCOUNTERS, analyze_fights, resolve_report_window


class RaidSelectionTests(unittest.TestCase):
    def test_season_two_filters_mixed_reports_at_each_difficulty(self):
        abyss = [3470, 3445, 3497, 3455, 3420, 3421, 3429, 3492]
        for difficulty in (3, 4, 5):
            with self.subTest(difficulty=difficulty):
                fights = [
                    {"boss": boss, "difficulty": difficulty, "zoneID": 3004}
                    for boss in abyss
                ] + [
                    {"boss": 3379, "difficulty": difficulty, "zoneID": 2987},
                    {"boss": 3513, "difficulty": difficulty, "zoneID": 3095},
                    {"boss": 3176, "difficulty": difficulty, "zoneID": 2912},
                    {"boss": 99999, "difficulty": difficulty, "zoneID": 3004},
                    {"boss": 0, "difficulty": difficulty, "zoneID": 3004},
                    {"boss": 3470, "difficulty": 1, "zoneID": 3004},
                    {"boss": 3379, "difficulty": 1, "zoneID": 2987},
                ]
                self.assertEqual(
                    [f["boss"] for f in analyze_fights(fights, "0", difficulty, "midnight-s2-all")],
                    abyss + [3379, 3513],
                )

    def test_known_encounters_work_without_game_zone(self):
        for boss in (3470, 3379, 3513):
            with self.subTest(boss=boss):
                fight = {"boss": boss, "difficulty": 4, "zoneID": None}
                self.assertEqual(analyze_fights([fight], "0", "4", "midnight-s2-all"), [fight])

    def test_earlier_raids_exclude_season_two_fights(self):
        new_fights = [
            {"boss": 3470, "difficulty": 5, "zoneID": 3004},
            {"boss": 3379, "difficulty": 5, "zoneID": 2987},
            {"boss": 3513, "difficulty": 5, "zoneID": 3095},
        ]
        for raid, allowed in RAID_ENCOUNTERS.items():
            if raid == "midnight-s2-all":
                continue
            with self.subTest(raid=raid):
                old = {"boss": next(iter(allowed)), "difficulty": 5, "zoneID": None}
                self.assertEqual(analyze_fights([old] + new_fights, "0", 5, raid), [old])

    def test_unknown_raid_retains_instance_fallback(self):
        fights = [
            {"boss": 3470, "difficulty": 4, "zoneID": 3004},
            {"boss": 3379, "difficulty": 4, "zoneID": 2987},
        ]
        self.assertEqual(analyze_fights(fights, "2987", 4), [fights[1]])

    def test_season_two_default_and_custom_date_windows(self):
        for raid in ("midnight-s2-all",):
            with self.subTest(raid=raid):
                self.assertEqual(resolve_report_window(raid, "", ""), ("2026-08-13", None))
                self.assertEqual(
                    resolve_report_window(raid, "2026-01-01", "2026-09-12"),
                    ("2026-08-13", "2026-09-12"),
                )
                self.assertEqual(
                    resolve_report_window(raid, "2026-09-01", "2026-09-12"),
                    ("2026-09-01", "2026-09-12"),
                )

    def test_season_one_window_closes_after_season_two_opens(self):
        # Season 2's raids opened 2026-08-18; Season 1 ends 5 days later.
        for raid in ("midnight-all", "voidspire", "dreamrift", "queldanas"):
            with self.subTest(raid=raid):
                self.assertEqual(resolve_report_window(raid, "", ""), ("2026-03-12", "2026-08-23"))
                self.assertEqual(
                    resolve_report_window(raid, "2026-04-01", "2026-12-01"),
                    ("2026-04-01", "2026-08-23"),
                )

    def test_only_the_newest_tier_is_open_ended(self):
        newest = max(start for start, _ in RAID_DATE_WINDOWS.values())
        for raid, (start, end) in RAID_DATE_WINDOWS.items():
            if start != newest:
                with self.subTest(raid=raid):
                    self.assertIsNotNone(end, f"{raid} has no end date but a newer tier exists")


class ReportDayTests(unittest.TestCase):
    """The chosen dates are days on the visitor's clock, and a log belongs to the day it started."""

    # 2026-11-03 in New York (UTC-5): 05:00 UTC Nov 3 to 04:59:59.999 UTC Nov 4.
    DAY_START = 1793682000000
    DAY_END = 1793768399999

    def fetch(self, reports):
        sent = {}

        def fake_query(token, query, variables):
            sent.update(variables)
            return {"reportData": {"reports": {"data": reports}}}

        with mock.patch.object(warcraftlogs, "graphql_query", side_effect=fake_query):
            got = warcraftlogs.get_guild_reports("t", "Guild", "Area 52", "us",
                                                 "2026-11-03", "2026-11-03", 300, 300)
        return sent, [r["id"] for r in got]

    def test_dates_are_the_visitors_days(self):
        sent, _ = self.fetch([])
        self.assertEqual((sent["startTime"], sent["endTime"]), (self.DAY_START, self.DAY_END))

    def test_last_nights_log_is_not_tonights(self):
        hour = 3600000
        _, ids = self.fetch([
            # Last night, 8 PM to 11:30 PM New York: already Nov 3 in UTC.
            {"code": "last", "startTime": self.DAY_START - 4 * hour, "endTime": self.DAY_START - hour // 2},
            # Started 11:30 PM last night and ran past midnight: still last night's log.
            {"code": "late", "startTime": self.DAY_START - hour // 2, "endTime": self.DAY_START + hour},
            # Tonight, 8 PM to 11:30 PM New York: already Nov 4 in UTC.
            {"code": "tonight", "startTime": self.DAY_START + 20 * hour, "endTime": self.DAY_START + 23 * hour},
        ])
        self.assertEqual(ids, ["tonight"])

    def test_no_offset_reads_utc_days(self):
        with mock.patch.object(warcraftlogs, "graphql_query", return_value={}) as q:
            warcraftlogs.get_guild_reports("t", "Guild", "Area 52", "us", "2026-11-03", "2026-11-03")
        variables = q.call_args[0][2]
        self.assertEqual((variables["startTime"], variables["endTime"]),
                         (self.DAY_START - 5 * 3600000, self.DAY_END - 5 * 3600000))


if __name__ == "__main__":
    unittest.main()
