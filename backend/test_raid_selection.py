import unittest
from analysis import RAID_ENCOUNTERS, analyze_fights, resolve_report_window


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
                    {"boss": 3176, "difficulty": difficulty, "zoneID": 2912},
                    {"boss": 99999, "difficulty": difficulty, "zoneID": 3004},
                    {"boss": 0, "difficulty": difficulty, "zoneID": 3004},
                    {"boss": 3470, "difficulty": 1, "zoneID": 3004},
                    {"boss": 3379, "difficulty": 1, "zoneID": 2987},
                ]
                self.assertEqual(
                    [f["boss"] for f in analyze_fights(fights, "0", difficulty, "midnight-s2-all")],
                    abyss + [3379],
                )

    def test_known_encounters_work_without_game_zone(self):
        for boss in (3470, 3379):
            with self.subTest(boss=boss):
                fight = {"boss": boss, "difficulty": 4, "zoneID": None}
                self.assertEqual(analyze_fights([fight], "0", "4", "midnight-s2-all"), [fight])

    def test_earlier_raids_exclude_season_two_fights(self):
        new_fights = [
            {"boss": 3470, "difficulty": 5, "zoneID": 3004},
            {"boss": 3379, "difficulty": 5, "zoneID": 2987},
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


if __name__ == "__main__":
    unittest.main()
