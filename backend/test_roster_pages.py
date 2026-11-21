import unittest
from unittest import mock

import warcraftlogs


class RosterPagesTests(unittest.TestCase):
    """Each roster page costs a WCL point: page 1 says how many there are, and no page past the last is read."""

    def _roster(self, last_page, fail=()):
        asked = []

        def fake(token, query, variables=None, **_):
            page = variables["page"]
            asked.append(page)
            if page in fail:
                raise Exception("timeout")
            members = [{"name": f"P{page}x{i}"} for i in range(100 if page < last_page else 7)] \
                if page <= last_page else []
            return {"guildData": {"guild": {"members": {"last_page": last_page, "data": members}}}}
        with mock.patch.object(warcraftlogs, "graphql_query", side_effect=fake):
            names = warcraftlogs.get_guild_roster("t", "G", "Area 52", "us")
        return sorted(asked), names

    def test_a_one_page_guild_reads_one_page(self):
        asked, names = self._roster(1)
        self.assertEqual(asked, [1])
        self.assertEqual(len(names), 7)

    def test_every_page_up_to_the_last(self):
        asked, names = self._roster(7)
        self.assertEqual(asked, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(len(names), 607)

    def test_an_unreadable_first_page_reads_every_page_it_can(self):
        asked, names = self._roster(2, fail={1})
        self.assertEqual(asked, list(range(1, 13)))
        self.assertEqual(len(names), 7)


if __name__ == "__main__":
    unittest.main()
