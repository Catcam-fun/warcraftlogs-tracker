"""
ratelimit.py - Per-client sliding-window limits for endpoints that write.

In-memory and per-process: good enough to stop a script from filling the
shares table or hammering WarcraftLogs through us, without new infra.
"""

import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import jsonify, request


def client_ip():
    # Render sits behind Cloudflare, which sets CF-Connecting-IP to the real
    # client and overwrites any value the client sent. X-Forwarded-For is not
    # usable: Render appends to whatever the client put there, so its first
    # entry can be forged. Without Cloudflare (local dev), use the socket.
    return (request.headers.get('CF-Connecting-IP', '').strip()
            or request.remote_addr or 'unknown')


class RateLimiter:
    def __init__(self, max_calls, per_seconds):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.time()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.per_seconds:
                hits.popleft()
            if len(hits) >= self.max_calls:
                return False
            hits.append(now)
            if len(self._hits) > 10000:  # drop idle clients so memory stays bounded
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
            return True


def limit(limiter, message):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method != 'OPTIONS' and not limiter.allow(client_ip()):
                return jsonify({"success": False, "error": message}), 429
            return fn(*args, **kwargs)
        return wrapper
    return decorator
