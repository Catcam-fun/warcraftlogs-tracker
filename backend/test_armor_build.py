import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import build_armor_constants as bac  # noqa: E402


class FakeWCL:
    """Mimics WCL: a fightIDs-scoped events query without an endTime gets an empty second page."""

    FIGHT = {"startTime": 1000, "endTime": 9000}
    EVENTS = [{"timestamp": t} for t in range(1000, 9000, 100)]   # 80 events
    PAGE = 30

    def __init__(self):
        self.event_calls = []

    def __call__(self, token, query, variables=None, **kw):
        if "fights(" in query:
            return {"reportData": {"report": {"fights": [dict(self.FIGHT)]}}}
        self.event_calls.append(dict(variables))
        start = variables.get("s") or self.FIGHT["startTime"]
        if variables.get("s") and variables.get("e") is None:
            return {"reportData": {"report": {"events": {"data": [], "nextPageTimestamp": None}}}}
        page = [e for e in self.EVENTS if e["timestamp"] >= start][: self.PAGE]
        rest = [e for e in self.EVENTS if e["timestamp"] > page[-1]["timestamp"]] if page else []
        nxt = rest[0]["timestamp"] if rest else None
        return {"reportData": {"report": {"events": {"data": page, "nextPageTimestamp": nxt}}}}


class ArmorBuildEventsTests(unittest.TestCase):
    def test_reads_every_page_of_a_fight(self):
        fake = FakeWCL()
        with mock.patch.object(bac, "graphql_query", fake):
            events = bac._events("tok", "CODE", 7)
        self.assertEqual(len(events), len(FakeWCL.EVENTS))
        self.assertGreater(len(fake.event_calls), 1)
        for call in fake.event_calls:
            self.assertEqual(call.get("e"), FakeWCL.FIGHT["endTime"])


if __name__ == "__main__":
    unittest.main()
