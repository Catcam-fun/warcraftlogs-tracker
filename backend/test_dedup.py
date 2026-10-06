import unittest

from analysis import dedup_pulls


def pull(rid, start, boss=1, length=60_000):
    return {"reportId": rid, "boss_id": boss, "abs_start": start, "abs_end": start + length, "is_kill": False}


class DedupPullsTests(unittest.TestCase):
    def test_each_pull_comes_from_the_fullest_log(self):
        # Two raiders logged the same night; B sat out the third pull, and
        # B's copies start a little earlier (the old pick, by start, chose them).
        night = [0, 300_000, 600_000]
        a = [pull("A", t) for t in night]
        b = [pull("B", t - 500) for t in night[:2]]
        kept = dedup_pulls(b + a)
        self.assertEqual([(p["reportId"], p["abs_start"]) for p in kept],
                         [("A", 0), ("A", 300_000), ("A", 600_000)])

    def test_another_log_fills_in_pulls_the_fullest_lacks(self):
        a = [pull("A", t) for t in (0, 300_000, 600_000)]
        b = [pull("B", t + 200) for t in (0, 900_000)]       # A's logger missed the last pull
        kept = dedup_pulls(a + b)
        self.assertEqual([(p["reportId"], p["abs_start"]) for p in kept],
                         [("A", 0), ("A", 300_000), ("A", 600_000), ("B", 900_200)])

    def test_different_bosses_at_once_are_not_duplicates(self):
        kept = dedup_pulls([pull("A", 0, boss=1), pull("B", 0, boss=2)])
        self.assertEqual(len(kept), 2)


if __name__ == "__main__":
    unittest.main()
