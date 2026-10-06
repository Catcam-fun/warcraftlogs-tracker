import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import build_defensive_catalog as bdc  # noqa: E402


class WagoCacheTests(unittest.TestCase):
    def test_live_tables_are_never_served_from_cache(self):
        # "Live" changes with every game build: a cached copy would go stale.
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bdc, "CACHE_DIR", d), \
                mock.patch.object(bdc, "_get", side_effect=[b"ID\n1\n", b"ID\n2\n"]) as get:
            self.assertEqual(bdc.table("SpellMisc"), [{"ID": "1"}])
            self.assertEqual(bdc.table("SpellMisc"), [{"ID": "2"}])
        self.assertEqual(get.call_count, 2)

    def test_pinned_builds_are_cached(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bdc, "CACHE_DIR", d), \
                mock.patch.object(bdc, "_get", return_value=b"ID\n1\n") as get:
            bdc.table("SpellMisc", "12.1.0.1")
            self.assertEqual(bdc.table("SpellMisc", "12.1.0.1"), [{"ID": "1"}])
        self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
