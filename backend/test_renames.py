"""Renamed players: one character under several names across a guild's reports counts as one player."""
import unittest

from analysis import current_names


def meta(start, *players):
    return {"report_start": start,
            "friendlies": [{"id": i, "name": n, "gameID": g, "server": s} for i, n, g, s in players]}


class CurrentNamesTests(unittest.TestCase):
    def test_old_name_takes_the_newest_name(self):
        metas = {"R1": meta(1_000, (10, "Ilovepriest", 555, "Area 52")),
                 "R2": meta(9_000, (4, "Ilovedragon", 555, "Area 52"))}
        self.assertEqual(current_names(metas), {"R1": {10: "Ilovedragon"}})

    def test_newest_name_wins_whatever_the_order_reports_were_read(self):
        metas = {"R2": meta(9_000, (4, "Ilovedragon", 555, "Area 52")),
                 "R1": meta(1_000, (10, "Ilovepriest", 555, "Area 52"))}
        self.assertEqual(current_names(metas), {"R1": {10: "Ilovedragon"}})

    def test_same_id_on_another_server_is_someone_else(self):
        metas = {"R1": meta(1_000, (10, "Ilovepriest", 555, "Area 52")),
                 "R2": meta(9_000, (4, "Ilovedragon", 555, "Illidan"))}
        self.assertEqual(current_names(metas), {})

    def test_players_without_an_id_or_server_are_left_alone(self):
        metas = {"R1": meta(1_000, (10, "Amy", None, "Area 52"), (11, "Bob", 7, None)),
                 "R2": meta(9_000, (4, "Amyx", None, "Area 52"), (5, "Bobx", 7, None))}
        self.assertEqual(current_names(metas), {})

    def test_a_freed_up_name_taken_by_someone_else_stays_theirs(self):
        # Ilovepriest renamed to Ilovedragon; later a different character took the name Ilovepriest.
        metas = {"R1": meta(1_000, (10, "Ilovepriest", 555, "Area 52")),
                 "R2": meta(9_000, (4, "Ilovedragon", 555, "Area 52"), (6, "Ilovepriest", 777, "Area 52"))}
        self.assertEqual(current_names(metas), {"R1": {10: "Ilovedragon"}})

    def test_reports_cached_before_ids_were_read_are_left_alone(self):
        metas = {"R1": {"report_start": 1_000, "friendlies": [{"id": 10, "name": "Ilovepriest"}]},
                 "R2": meta(9_000, (4, "Ilovedragon", 555, "Area 52"))}
        self.assertEqual(current_names(metas), {})


if __name__ == "__main__":
    unittest.main()
