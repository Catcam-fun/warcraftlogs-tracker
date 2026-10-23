import unittest
from unittest import mock

import testenv  # noqa: F401  (before any backend import)
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


class CappedCacheTable:
    """The `report_cache` table as Supabase serves it: at most 1,000 rows per request."""
    MAX_ROWS = 1000

    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _CappedQuery(self)


class _CappedQuery:
    def __init__(self, db):
        self.db, self.op, self.orders, self.span, self.keys = db, 'select', [], None, None

    def select(self, *_a, **_k):
        return self

    def order(self, col, desc=False):
        self.orders.append((col, desc))
        return self

    def range(self, start, end):
        self.span = (start, end)
        return self

    def delete(self):
        self.op = 'delete'
        return self

    def in_(self, col, values):
        self.keys = (col, set(values))
        return self

    def execute(self):
        if self.op == 'delete':
            col, values = self.keys
            self.db.rows[:] = [r for r in self.db.rows if r[col] not in values]
            return mock.Mock(data=[])
        rows = list(self.db.rows)
        for col, desc in reversed(self.orders):
            rows.sort(key=lambda r: r[col], reverse=desc)
        start, end = self.span or (0, len(rows) - 1)
        end = min(end, start + CappedCacheTable.MAX_ROWS - 1)
        return mock.Mock(data=[dict(r) for r in rows[start:end + 1]])


class ReportCacheEvictionTests(unittest.TestCase):
    def test_eviction_sees_every_row_past_the_first_thousand(self):
        # 2,500 rows of 100 KB (250 MB): the 452 least recently used must go to fit 200 MB.
        size = 100 * 1024
        rows = [{"key": f"k{i:04d}", "size_bytes": size, "last_used_at": f"2026-10-{1 + i // 100:02d}T{i % 100:02d}"}
                for i in range(2500)]
        db = CappedCacheTable(rows)
        with mock.patch.object(supabase_client, 'db', db):
            supabase_client.evict_report_cache()
        self.assertEqual(len(db.rows), supabase_client.REPORT_CACHE_BUDGET_BYTES // size)
        self.assertEqual(min(r["key"] for r in db.rows), "k0452")   # the oldest ones went

    def test_eviction_keeps_a_table_under_budget(self):
        rows = [{"key": f"k{i}", "size_bytes": 1024, "last_used_at": str(i)} for i in range(1500)]
        db = CappedCacheTable(rows)
        with mock.patch.object(supabase_client, 'db', db):
            supabase_client.evict_report_cache()
        self.assertEqual(len(db.rows), 1500)


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
