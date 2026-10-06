"""
cache.py - Small thread-safe LRU cache for WarcraftLogs report data.

A finished WCL report never changes, so re-running an analysis (or a
second officer running the same guild) can reuse fights and deaths
instead of downloading them again. Callers only cache reports that ended
a while ago; a report that is still being live-logged is always fetched.
Finished reports are also shared across server restarts and users through
Supabase (SharedReportCache), so each one is downloaded from WCL only once.
"""

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait


class LRUCache:
    def __init__(self, max_items):
        self.max_items = max_items
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key, value):
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def __len__(self):
        with self._lock:
            return len(self._data)


class SharedReportCache:
    """An LRUCache in front of the shared Supabase `report_cache` table.

    get() tries memory, then Supabase; set() writes both (Supabase in the
    background, so an analysis never waits on it). Keys are namespaced and
    versioned: bump CACHE_VERSION whenever what gets fetched or how it's
    indexed changes, so old rows are never served to new code.
    """

    def __init__(self, namespace, max_items, store=None):
        self.memory = LRUCache(max_items)
        self.namespace = namespace
        self._store = store

    @property
    def _data(self):          # tests clear the memory layer directly
        return self.memory._data

    def _key(self, key):
        return f"{CACHE_VERSION}:{self.namespace}:{key!r}"

    def _backend(self):
        if self._store is not None:
            return self._store
        import supabase_client
        return supabase_client

    def get(self, key):
        value = self.memory.get(key)
        if value is None:
            value = self._backend().cache_get(self._key(key))
            if value is not None:
                self.memory.set(key, value)
        return value

    def set(self, key, value):
        self.memory.set(key, value)
        future = _WRITER.submit(self._backend().cache_put, self._key(key), value)
        with _PENDING_LOCK:
            _PENDING.add(future)
        future.add_done_callback(_written)

    def __len__(self):
        return len(self.memory)


CACHE_VERSION = "v2"
_WRITER = ThreadPoolExecutor(max_workers=4, thread_name_prefix="report-cache")
_PENDING = set()
_PENDING_LOCK = threading.Lock()


def _written(future):
    with _PENDING_LOCK:
        _PENDING.discard(future)


def flush_writes(timeout=120):
    """Wait for the shared-cache writes queued so far. On Lambda the function
    is frozen once a response ends, so writes still queued then are lost:
    the analysis calls this after sending its result."""
    with _PENDING_LOCK:
        pending = list(_PENDING)
    if pending:
        wait(pending, timeout=timeout)


# Sized for Render's small instances: a report's fights+abilities entry is
# typically tens of KB, its deaths well under that.
report_meta_cache = SharedReportCache("meta", 200)
report_deaths_cache = SharedReportCache("deaths", 400)
# Casts, defensive buffs and talent loadouts, indexed by player.
report_defensive_cache = SharedReportCache("defensives", 200)
# Per report, indexed by player: the hits before the deaths that can count
# (lethal windows) and instant kills.
report_recap_cache = SharedReportCache("killing-blows", 400)
