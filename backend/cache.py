"""
cache.py - Small thread-safe LRU cache for WarcraftLogs report data.

A finished WCL report never changes, so re-running an analysis (or a
second officer running the same guild) can reuse fights and deaths
instead of downloading them again. Callers only cache reports that ended
a while ago; a report that is still being live-logged is always fetched.
"""

import threading
from collections import OrderedDict


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


# Sized for Render's small instances: a report's fights+abilities entry is
# typically tens of KB, its deaths well under that.
report_meta_cache = LRUCache(200)
report_deaths_cache = LRUCache(400)
# Casts, defensive buffs and talent loadouts, indexed by player.
report_defensive_cache = LRUCache(200)
