"""
auth.py - Verify the caller's Supabase session on protected endpoints.

The frontend sends `Authorization: Bearer <supabase access token>`. We ask
Supabase who that token belongs to (GET /auth/v1/user) instead of trusting a
user_id from the URL or body, so one user can never read, delete, or save
data as another. Verified tokens are cached briefly so a burst of requests
doesn't turn into a burst of Supabase round-trips.
"""

import hashlib
import os
import threading
import time
from functools import wraps

import requests
from flask import g, jsonify, request

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

_CACHE_TTL = 60          # seconds a verified token is trusted without re-checking
_CACHE_MAX = 1000
_cache = {}              # sha256(token) -> (user_id, expires_at)
_lock = threading.Lock()


def _bearer_token():
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip() or None
    return None


def verify_token(token):
    """Return the Supabase user id for `token`, or None if it isn't valid."""
    if not token or not SUPABASE_URL or not SUPABASE_KEY:
        return None

    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[1] > now:
            return hit[0]

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {token}'},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"[Auth] Supabase verification request failed: {e}")
        return None
    if resp.status_code != 200:
        return None

    user_id = (resp.json() or {}).get('id')
    if not user_id:
        return None

    with _lock:
        if len(_cache) >= _CACHE_MAX:
            for k in [k for k, (_, exp) in _cache.items() if exp <= now] or list(_cache)[:_CACHE_MAX // 2]:
                _cache.pop(k, None)
        _cache[key] = (user_id, now + _CACHE_TTL)
    return user_id


def forget_token(token):
    """Drop a token from the cache (e.g. after its account is deleted)."""
    if token:
        with _lock:
            _cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)


def require_user(fn):
    """Route decorator: 401 unless the request carries a valid Supabase session.

    The verified id is available as `g.user_id`.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method == 'OPTIONS':
            return '', 204
        user_id = verify_token(_bearer_token())
        if not user_id:
            return jsonify({"success": False, "error": "Please sign in again."}), 401
        g.user_id = user_id
        return fn(*args, **kwargs)
    return wrapper
