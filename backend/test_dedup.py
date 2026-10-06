import unittest

from analysis import dedup_pulls


def pull(rid, start, end, boss=1, fid=1, kill=False):
    return {'reportId': rid, 'boss_id': boss, 'abs_start': start, 'abs_end': end, 'is_kill': kill,
            'fight': {'id': fid}}


class DedupPullsTests(unittest.TestCase):
    def test_earliest_copy_is_kept(self):
        a, b = pull('A', 1_000, 300_000), pull('B', 1_400, 300_300)
        self.assertEqual(dedup_pulls([a, b]), [a])

    def test_pull_only_one_log_has_is_kept(self):
        a, b = pull('A', 1_000, 300_000), pull('B', 900_000, 1_200_000)
        self.assertEqual(dedup_pulls([a, b]), [a, b])

    def test_other_boss_is_never_a_copy(self):
        a, b = pull('A', 1_000, 300_000, boss=1), pull('B', 1_000, 300_000, boss=2)
        self.assertEqual(dedup_pulls([a, b]), [a, b])

    def test_copy_cut_short_gives_way_to_the_full_one(self):
        # The earliest copy's logger stopped logging 84 s before the wipe ended.
        short, full = pull('A', 1_000, 174_000), pull('B', 1_200, 258_400)
        self.assertEqual(dedup_pulls([short, full]), [full])

    def test_clock_jitter_keeps_the_earliest_copy(self):
        a, b = pull('A', 1_000, 300_000), pull('B', 1_100, 301_000)    # 0.9 s longer: same pull
        self.assertEqual(dedup_pulls([a, b]), [a])

    def test_same_start_ties_go_by_report_code(self):
        a, b = pull('B', 1_000, 300_000), pull('A', 1_000, 300_000)
        self.assertEqual(dedup_pulls([a, b])[0]['reportId'], 'A')


if __name__ == '__main__':
    unittest.main()
