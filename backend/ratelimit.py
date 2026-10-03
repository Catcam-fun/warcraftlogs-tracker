"""
ratelimit.py - Per-client sliding-window limits for endpoints that write.

Each limiter counts in memory first. Named limiters are also counted in
Supabase (backend/migrations/003_rate_limits.sql), because on AWS Lambda
every concurrent request can land on a separate copy of the server, each
with its own memory. Until that table exists, or if Supabase is down, the
in-memory count alone decides.
"""

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import jsonify, request


def from_cloudfront():
    """True when the request carries the secret CloudFront adds on AWS."""
    secret = os.environ.get('ORIGIN_SECRET')
    sent = request.headers.get('X-Origin-Verify', '')
    return bool(secret) and hmac.compare_digest(sent.encode(), secret.encode())


def client_ip():
    # Behind CloudFront: the address a CloudFront Function stamps on every API
    # request (aws/template.yaml). X-Forwarded-For can't be used there, since
    # CloudFront keeps whatever the client sent in it and only appends.
    if from_cloudfront():
        viewer = request.headers.get('X-Viewer-Ip', '').strip()
        if viewer:
            return viewer
    # Render (and most hosts) put the real client first in X-Forwarded-For.
    forwarded = request.headers.get('X-Forwarded-For', '')
    return forwarded.split(',')[0].strip() or request.remote_addr or 'unknown'


class RateLimiter:
    def __init__(self, max_calls, per_seconds, name=None, store=None):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.name = name          # set: also counted in Supabase under this name
        self._store = store
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key):
        if not self._allow_local(key):
            return False
        return self._allow_shared(key) is not False

    def _allow_local(self, key):
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

    def _allow_shared(self, key):
        """True/False from Supabase, or None when it can't be asked."""
        if not self.name:
            return None
        store = self._store
        if store is None:
            import supabase_client as store
        # Only a hash of the address is stored.
        client = hashlib.sha256(key.encode()).hexdigest()
        return store.rate_limit_hit(self.name, client, self.max_calls, self.per_seconds)


def limit(limiter, message):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method != 'OPTIONS' and not limiter.allow(client_ip()):
                return jsonify({"success": False, "error": message}), 429
            return fn(*args, **kwargs)
        return wrapper
    return decorator
