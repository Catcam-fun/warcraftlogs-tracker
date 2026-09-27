import unittest
from analysis import rank_pull_deaths


def death(ts, who, cheat=False):
    return {"timestamp": ts, "targetID": who, "isCheatDeath": cheat}


def counted(deaths, x):
    return [d["targetID"] + ("*" if d["isCheatDeath"] else "")
            for d, (slot, wipe) in zip(deaths, rank_pull_deaths(deaths)) if slot <= x and not wipe]


class DeathSlotTests(unittest.TestCase):
    def test_cheat_deaths_never_push_real_deaths_out(self):
        # A dies, B cheats, C dies: first 2 = A and C, plus B's cheat death.
        deaths = [death(10, "A"), death(20, "B", True), death(30, "C"), death(40, "D")]
        self.assertEqual(counted(deaths, 2), ["A", "B*", "C"])

    def test_cheat_death_after_the_cutoff_does_not_count(self):
        deaths = [death(10, "A"), death(20, "C"), death(30, "B", True)]
        self.assertEqual(counted(deaths, 2), ["A", "C"])

    def test_simultaneous_deaths_take_one_slot_each_in_log_order(self):
        # Fight 38 of Fhj4Ry3gX8NLbG7W: deaths 2 and 3 on the same millisecond.
        deaths = [death(72100, "Joicountdown"), death(90100, "Titus"), death(90100, "Shoodini")]
        self.assertEqual(counted(deaths, 2), ["Joicountdown", "Titus"])

    def test_player_rezzed_and_dying_again_takes_both_slots(self):
        deaths = [death(83880, "Chispade"), death(111110, "Chispade"), death(114040, "Rarelywright")]
        self.assertEqual(counted(deaths, 2), ["Chispade", "Chispade"])

    def test_wipe_deaths_never_count_and_cheats_do_not_make_a_wipe(self):
        deaths = [death(1_000, "A")] + [death(50_000 + i, f"W{i}") for i in range(8)]
        self.assertEqual(counted(deaths, 3), ["A"])
        # Seven real deaths plus a cheat death is not a wipe.
        deaths = [death(49_999, "R", True)] + [death(50_000 + i, f"W{i}") for i in range(7)]
        self.assertEqual(counted(deaths, 1), ["R*", "W0"])

    def test_cheat_death_inside_a_wipe_does_not_count(self):
        deaths = [death(1_000, "A")] + [death(50_000 + i, f"W{i}") for i in range(4)] + \
                 [death(50_005, "R", True)] + [death(50_010 + i, f"V{i}") for i in range(4)]
        self.assertEqual(counted(deaths, 2), ["A"])

    def test_cheat_death_just_before_a_wipe_does_not_count(self):
        # Pull 19 of H8gCzVa7Y4JDf61X: Squidfear dies at 0:52; Xanq's Cheat Death
        # procs at 1:42.115, a few ms before the wipe's first death (1:42.123).
        deaths = [death(52_356, "Squidfear"), death(102_115, "Xanq", True)] + \
                 [death(102_123 + i * 300, f"W{i}") for i in range(10)]
        self.assertEqual(counted(deaths, 2), ["Squidfear"])


if __name__ == "__main__":
    unittest.main()
