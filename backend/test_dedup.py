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

    def test_logs_whose_clocks_disagree_are_matched_pull_for_pull(self):
        # Unluck's two logs of 2026-11-04: the second logger's clock ran ~90.5 s ahead, so each copy overlapped
        # its own pull by less than half and the next pull too. Ula'tek pulls 28-30, from the live log.
        a = [pull('T', 1_000_000, 1_073_000, fid=28), pull('T', 1_117_000, 1_302_000, fid=29),
             pull('T', 1_383_000, 1_628_000, fid=30)]
        b = [pull('J', s + 90_400, e + 90_400 + 50, fid=f) for s, e, f in
             ((1_000_000, 1_073_000, 28), (1_117_000, 1_302_000, 29), (1_383_000, 1_628_000, 30))]
        self.assertEqual(dedup_pulls(a + b), a)      # each pull once: the copy that started first on its own clock

    def test_a_small_clock_gap_keeps_the_same_copy_as_before(self):
        # Honestly's logs were 1.4 s apart: the overlap rules already matched them, and the copy kept must not
        # change because one log's clock was read as behind.
        a = [pull('A', 1_000_000 + i * 400_000, 1_200_000 + i * 400_000 + i * 7_000, fid=i) for i in range(3)]
        b = [dict(p, reportId='B', abs_start=p['abs_start'] + 1_400, abs_end=p['abs_end'] + 1_400) for p in a]
        self.assertEqual(dedup_pulls(b + a), a)
        z = [dict(p, reportId='Z') for p in a]                   # same start: ties still go by report code
        self.assertEqual(dedup_pulls(z + b + a), a)

    def test_clock_gap_is_read_per_pair_of_logs(self):
        a = [pull('A', 1_000_000 + i * 400_000, 1_200_000 + i * 400_000 + i * 7_000, fid=i) for i in range(3)]
        b = [dict(p, reportId='B', abs_start=p['abs_start'] + 60_000, abs_end=p['abs_end'] + 60_000) for p in a]
        c = [dict(p, reportId='C', abs_start=p['abs_start'] - 45_000, abs_end=p['abs_end'] - 45_000) for p in a]
        self.assertEqual(dedup_pulls(b + c + a), c)          # three pulls, not nine; C's copies started first

    def test_one_matching_length_is_not_a_clock_gap(self):
        # Two different pulls that happen to last the same: no shift, both kept.
        a, b = pull('A', 1_000, 200_000), pull('B', 400_000, 599_000)
        self.assertEqual(dedup_pulls([a, b]), [a, b])

    def test_shifted_copy_cut_short_still_gives_way(self):
        # B's clock is 90 s ahead; A's logger stopped 100 s before the last wipe ended, so B's copy is kept.
        a = [pull('A', 1_000_000, 1_200_000, fid=1), pull('A', 1_500_000, 1_800_000, fid=2),
             pull('A', 2_000_000, 2_150_000, fid=3)]
        b = [pull('B', 1_090_000, 1_290_000, fid=1), pull('B', 1_590_000, 1_890_000, fid=2),
             pull('B', 2_090_000, 2_340_000, fid=3)]
        self.assertEqual(dedup_pulls(a + b), [a[0], a[1], b[2]])


if __name__ == '__main__':
    unittest.main()
