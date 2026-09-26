"""
supabase_client.py - Supabase storage for saved analyses, shares, and accounts.

All access goes through the service-role key on the server, and every call
is scoped to a user id that auth.py has already verified. The tables
themselves have row-level security on with no anon policies (see
backend/migrations/), so the public anon key in the frontend can't read them.

Payloads are stored brotli-compressed ("br64:" + base64) to keep Supabase
usage small; plain-JSON rows written by older versions still load.
"""

import base64
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import brotli
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')

MAX_SAVED_PER_USER = 5
MAX_SAVED_BYTES = 3 * 1024 * 1024    # compressed
MAX_SHARE_BYTES = 2 * 1024 * 1024    # compressed
SHARE_TTL_HOURS = 72

# Prefer the service-role key: RLS stays on for these tables and only the
# server (which checks who the caller is) can touch them.
_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
db: Client = create_client(SUPABASE_URL, _key) if SUPABASE_URL and _key else None
print(f"[Startup] Supabase storage configured: {db is not None} "
      f"(service role: {bool(SUPABASE_SERVICE_ROLE_KEY)})")


def is_configured():
    return db is not None


def _now():
    return datetime.now(timezone.utc)


# =============================================================================
# PAYLOAD HELPERS
# =============================================================================

# Config keys that must never be stored or shared.
_SECRET_KEYS = {'clientid', 'clientsecret', 'client_id', 'client_secret',
                'password', 'token', 'accesstoken', 'access_token'}


def strip_secrets(config):
    """Return a copy of an analysis config without credentials."""
    if not isinstance(config, dict):
        return None
    return {k: v for k, v in config.items() if k.lower() not in _SECRET_KEYS}


def pack(obj):
    raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    return 'br64:' + base64.b64encode(brotli.compress(raw, quality=9)).decode('ascii')


def unpack(text):
    if not text:
        return None
    if isinstance(text, str) and text.startswith('br64:'):
        return json.loads(brotli.decompress(base64.b64decode(text[5:])))
    return json.loads(text) if isinstance(text, str) else text


# =============================================================================
# SAVED ANALYSES (max 5 per user)
# =============================================================================

def _purge_expired_saves(user_id):
    db.table('saved_analyses').delete().eq('user_id', user_id).lt('expires_at', _now().isoformat()).execute()


def save_analysis(user_id, analysis_name, guild_name, analysis_data, config=None, retention_days=30):
    if not db:
        return {"error": "Database not configured"}
    try:
        retention_days = max(1, min(int(retention_days or 30), 30))
        _purge_expired_saves(user_id)

        existing = db.table('saved_analyses').select('id', count='exact').eq('user_id', user_id).execute()
        if (existing.count or 0) >= MAX_SAVED_PER_USER:
            return {"error": f"You can keep {MAX_SAVED_PER_USER} saved reports. Delete one to save another.",
                    "code": "limit"}

        blob = pack({"data": analysis_data, "config": strip_secrets(config)})
        if len(blob) > MAX_SAVED_BYTES:
            return {"error": "This analysis is too large to save.", "code": "too_large"}

        analysis_id = str(uuid.uuid4())
        db.table('saved_analyses').insert({
            'id': analysis_id,
            'user_id': user_id,
            'analysis_name': (analysis_name or 'Untitled')[:100],
            'guild_name': (guild_name or '')[:100],
            'analysis_data': blob,
            'retention_days': retention_days,
            'size_bytes': len(blob),
            'expires_at': (_now() + timedelta(days=retention_days)).isoformat(),
        }).execute()
        return {"success": True, "id": analysis_id, "size_bytes": len(blob)}
    except Exception as e:
        print(f"[Saved] save failed: {e}")
        return {"error": "Could not save the report."}


def get_user_analyses(user_id):
    if not db:
        return {"error": "Database not configured"}
    try:
        _purge_expired_saves(user_id)
        result = db.table('saved_analyses').select(
            'id, analysis_name, guild_name, created_at, expires_at, retention_days, size_bytes'
        ).eq('user_id', user_id).order('created_at', desc=True).execute()
        return {"success": True, "analyses": result.data or [], "limit": MAX_SAVED_PER_USER}
    except Exception as e:
        print(f"[Saved] list failed: {e}")
        return {"error": "Could not load saved reports."}


def load_analysis(analysis_id, user_id):
    if not db:
        return {"error": "Database not configured"}
    try:
        result = db.table('saved_analyses').select('*') \
            .eq('id', analysis_id).eq('user_id', user_id).limit(1).execute()
        if not result.data:
            return {"error": "Report not found", "code": "not_found"}
        row = result.data[0]
        payload = unpack(row.get('analysis_data'))
        # Rows from older versions stored the bare analysis without a config.
        if not (isinstance(payload, dict) and 'data' in payload and 'meta' not in payload):
            payload = {"data": payload, "config": None}
        return {
            "success": True,
            "analysis_name": row.get('analysis_name'),
            "guild_name": row.get('guild_name'),
            "data": payload.get('data'),
            "config": strip_secrets(payload.get('config')),
            "created_at": row.get('created_at'),
            "expires_at": row.get('expires_at'),
        }
    except Exception as e:
        print(f"[Saved] load failed: {e}")
        return {"error": "Could not load the report."}


def delete_analysis(analysis_id, user_id):
    if not db:
        return {"error": "Database not configured"}
    try:
        db.table('saved_analyses').delete().eq('id', analysis_id).eq('user_id', user_id).execute()
        return {"success": True}
    except Exception as e:
        print(f"[Saved] delete failed: {e}")
        return {"error": "Could not delete the report."}


def delete_all_analyses(user_id):
    if not db:
        return {"error": "Database not configured"}
    try:
        db.table('saved_analyses').delete().eq('user_id', user_id).execute()
        return {"success": True}
    except Exception as e:
        print(f"[Saved] delete-all failed: {e}")
        return {"error": "Could not delete saved reports."}


# =============================================================================
# SHARES (72h, compressed, in the `shared_results` table)
# =============================================================================
#
# If the table hasn't been created yet (run backend/migrations/001_*.sql),
# shares fall back to process memory so the feature degrades rather than
# breaks, but those shares vanish whenever the server restarts.

_mem_shares = {}
_mem_lock = threading.Lock()


def _mem_put(share_id, blob):
    with _mem_lock:
        now = time.time()
        for k in [k for k, (_, exp) in _mem_shares.items() if exp < now]:
            del _mem_shares[k]
        _mem_shares[share_id] = (blob, now + SHARE_TTL_HOURS * 3600)


def _mem_get(share_id):
    with _mem_lock:
        hit = _mem_shares.get(share_id)
        if hit and hit[1] > time.time():
            return hit[0]
    return None


def store_share(share_id, data, config, user_id=None):
    blob = pack({"data": data, "config": strip_secrets(config)})
    if len(blob) > MAX_SHARE_BYTES:
        return {"error": "This analysis is too large to share.", "code": "too_large"}
    expires_at = _now() + timedelta(hours=SHARE_TTL_HOURS)
    if db:
        try:
            # Cheap housekeeping: expired shares are removed as new ones arrive.
            db.table('shared_results').delete().lt('expires_at', _now().isoformat()).execute()
            db.table('shared_results').insert({
                'id': share_id,
                'payload': blob,
                'size_bytes': len(blob),
                'created_by': user_id,
                'expires_at': expires_at.isoformat(),
            }).execute()
            return {"success": True, "expires_at": expires_at.isoformat()}
        except Exception as e:
            print(f"[Share] Supabase insert failed, using memory fallback: {e}")
    _mem_put(share_id, blob)
    return {"success": True, "expires_at": expires_at.isoformat(), "ephemeral": True}


def get_share(share_id):
    blob, created_at = _mem_get(share_id), None
    if blob is None and db:
        try:
            result = db.table('shared_results').select('payload, created_at, expires_at') \
                .eq('id', share_id).gt('expires_at', _now().isoformat()).limit(1).execute()
            if result.data:
                blob = result.data[0]['payload']
                created_at = result.data[0].get('created_at')
        except Exception as e:
            print(f"[Share] Supabase lookup failed: {e}")
    if blob is None:
        return None
    payload = unpack(blob)
    return {"data": payload.get('data'), "config": strip_secrets(payload.get('config')),
            "created_at": created_at}


# =============================================================================
# ACCOUNT DELETION
# =============================================================================

def delete_user_account(user_id):
    """Delete every row we hold for `user_id`, then the auth user itself."""
    if not db:
        return {"error": "Database not configured"}
    if not SUPABASE_SERVICE_ROLE_KEY:
        return {"error": "Account deletion isn't configured on the server."}

    errors = []
    for table in ('saved_analyses', 'api_credentials'):
        try:
            db.table(table).delete().eq('user_id', user_id).execute()
        except Exception as e:
            errors.append(f"{table}: {e}")
    try:
        # Shares expire on their own; this only fails if the table is missing.
        db.table('shared_results').delete().eq('created_by', user_id).execute()
    except Exception as e:
        print(f"[Delete Account] shared_results cleanup skipped: {e}")
    try:
        db.auth.admin.delete_user(user_id)
    except Exception as e:
        errors.append(f"auth: {e}")

    if errors:
        print(f"[Delete Account] partial failure for {user_id}: {errors}")
        return {"error": "Some account data could not be deleted. Please try again."}
    return {"success": True}
