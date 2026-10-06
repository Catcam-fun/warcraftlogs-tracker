import unittest
from unittest import mock

import cache
import supabase_client


class FakeStore:
    def __init__(self):
        self.rows = {}

    def cache_get(self, key):
        return self.rows.get(key)

    def cache_put(self, key, value):
        self.rows[key] = value


class SharedReportCacheTests(unittest.TestCase):
    def test_round_trip_keeps_int_and_tuple_keys(self):
        value = {"talents": {(7, 12): {96161: 2}}, "casts": {12: [(1000, 48707)]},
                 "names": {"Bob": 1}, "set": {1, 2}, "list": [1, (2, 3)]}
        packed = supabase_client.pack(supabase_client._enc(value))
        self.assertEqual(supabase_client._dec(supabase_client.unpack(packed)), value)

    def test_memory_then_shared_store(self):
        store = FakeStore()
        first = cache.SharedReportCache("deaths", 10, store=store)
        first.set(("R1", (1, 2)), {1: ["death"]})
        cache.flush_writes()                              # wait for the background write
        # A fresh server (empty memory) finds it in the shared store.
        second = cache.SharedReportCache("deaths", 10, store=store)
        self.assertEqual(second.get(("R1", (1, 2))), {1: ["death"]})
        self.assertIsNone(second.get(("R2", (1, 2))))

    def test_keys_are_namespaced_and_versioned(self):
        store = FakeStore()
        cache.SharedReportCache("meta", 10, store=store).set("R1", {"a": 1})
        cache.flush_writes()
        self.assertIsNone(cache.SharedReportCache("deaths", 10, store=store).get("R1"))
        self.assertTrue(all(k.startswith(cache.CACHE_VERSION + ":") for k in store.rows))

    def test_missing_database_is_a_cache_miss(self):
        orig = supabase_client.db
        supabase_client.db = None
        try:
            self.assertIsNone(supabase_client.cache_get("x"))
            supabase_client.cache_put("x", {"a": 1})      # no error
        finally:
            supabase_client.db = orig


if __name__ == "__main__":
    unittest.main()


class ReportCacheConnectionTests(unittest.TestCase):
    """A reset connection is retried; the shared cache isn't switched off for it."""

    def test_reset_connection_is_retried(self):
        import supabase_client
        from test_api import FakeDB, FakeResult

        class FlakyDB(FakeDB):
            fails = 2

            def table(self, name):
                q = super().table(name)
                real = q.execute

                def execute():
                    if FlakyDB.fails:
                        FlakyDB.fails -= 1
                        raise ConnectionResetError(104, "Connection reset by peer")
                    return real()
                q.execute = execute
                return q

        flaky = FlakyDB()
        flaky.tables['report_cache'] = [{'key': 'k1', 'payload': supabase_client.pack({"a": 1})}]
        with mock.patch.object(supabase_client, 'db', flaky), \
                mock.patch.object(supabase_client, '_cache_disabled_until', 0.0), \
                mock.patch.object(supabase_client.time, 'sleep'):
            self.assertEqual(supabase_client.cache_get('k1'), {"a": 1})
            self.assertTrue(supabase_client._cache_available())
