"""
supabase_client.py - Supabase database operations
"""

import os
import requests
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Environment variables
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')

# Initialize client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("[Startup] Supabase client initialized")
else:
    print("[Startup] Supabase not configured")


def is_configured():
    """Check if Supabase is configured."""
    return supabase is not None


# =============================================================================
# ANALYSIS STORAGE
# =============================================================================

def save_analysis(user_id, analysis_name, guild_name, analysis_data, retention_days=30):
    """Save an analysis to the database."""
    if not supabase:
        return {"error": "Database not configured"}
    
    try:
        import json
        import uuid
        from datetime import datetime, timedelta
        
        analysis_id = str(uuid.uuid4())
        data_json = json.dumps(analysis_data)
        size_bytes = len(data_json.encode('utf-8'))
        expires_at = datetime.utcnow() + timedelta(days=retention_days)
        
        result = supabase.table('saved_analyses').insert({
            'id': analysis_id,
            'user_id': user_id,
            'analysis_name': analysis_name,
            'guild_name': guild_name,
            'analysis_data': data_json,
            'retention_days': retention_days,
            'size_bytes': size_bytes,
            'expires_at': expires_at.isoformat()
        }).execute()
        
        return {"success": True, "analysis_id": analysis_id, "size_bytes": size_bytes}
    except Exception as e:
        return {"error": str(e)}


def load_analysis(analysis_id):
    """Load an analysis from the database."""
    if not supabase:
        return {"error": "Database not configured"}
    
    try:
        import json
        result = supabase.table('saved_analyses').select('*').eq('id', analysis_id).single().execute()
        if not result.data:
            return {"error": "Analysis not found"}
        
        data = result.data
        return {
            "success": True,
            "analysis_name": data.get('analysis_name'),
            "guild_name": data.get('guild_name'),
            "analysis_data": json.loads(data.get('analysis_data', '{}')),
            "created_at": data.get('created_at'),
            "expires_at": data.get('expires_at')
        }
    except Exception as e:
        return {"error": str(e)}


def get_user_analyses(user_id):
    """Get all analyses for a user."""
    if not supabase:
        return {"error": "Database not configured"}
    
    try:
        result = supabase.table('saved_analyses').select(
            'id, analysis_name, guild_name, created_at, expires_at, retention_days, size_bytes'
        ).eq('user_id', user_id).order('created_at', desc=True).execute()
        
        return {"success": True, "analyses": result.data or []}
    except Exception as e:
        return {"error": str(e)}


def delete_analysis(analysis_id):
    """Delete a single analysis."""
    if not supabase:
        return {"error": "Database not configured"}
    
    try:
        supabase.table('saved_analyses').delete().eq('id', analysis_id).execute()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def delete_all_analyses(user_id):
    """Delete all analyses for a user."""
    if not supabase:
        return {"error": "Database not configured"}
    
    try:
        supabase.table('saved_analyses').delete().eq('user_id', user_id).execute()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# USER ACCOUNT MANAGEMENT
# =============================================================================

def delete_user_account(user_id):
    """
    Delete user account and all associated data.
    Uses service_role key for admin privileges.
    """
    if not supabase:
        return {"error": "Database not configured"}
    
    if not SUPABASE_SERVICE_ROLE_KEY:
        print("[ERROR] SUPABASE_SERVICE_ROLE_KEY not set")
        return {"error": "Server configuration error: Missing admin privileges"}
    
    deletion_errors = []
    
    # Admin headers for all operations
    admin_headers = {
        'apikey': SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_ROLE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }
    
    # Step 1: Delete saved_analyses
    try:
        url = f"{SUPABASE_URL}/rest/v1/saved_analyses?user_id=eq.{user_id}"
        response = requests.delete(url, headers=admin_headers, timeout=10)
        print(f"[DEBUG] saved_analyses deletion: status={response.status_code}")
        if response.status_code not in [200, 204]:
            deletion_errors.append(f"saved_analyses: {response.status_code}")
        else:
            print(f"[OK] Deleted saved analyses for {user_id}")
    except Exception as e:
        deletion_errors.append(f"saved_analyses: {str(e)}")
    
    # Step 2: Delete api_credentials
    try:
        url = f"{SUPABASE_URL}/rest/v1/api_credentials?user_id=eq.{user_id}"
        response = requests.delete(url, headers=admin_headers, timeout=10)
        print(f"[DEBUG] api_credentials deletion: status={response.status_code}")
        if response.status_code not in [200, 204]:
            deletion_errors.append(f"api_credentials: {response.status_code}")
        else:
            print(f"[OK] Deleted API credentials for {user_id}")
    except Exception as e:
        deletion_errors.append(f"api_credentials: {str(e)}")
    
    # Step 3: Delete auth user
    try:
        url = f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}"
        response = requests.delete(url, headers=admin_headers, timeout=10)
        print(f"[DEBUG] Auth deletion: status={response.status_code}")
        if response.status_code not in [200, 204]:
            deletion_errors.append(f"auth: {response.status_code} - {response.text}")
        else:
            print(f"[OK] Deleted auth user {user_id}")
    except Exception as e:
        deletion_errors.append(f"auth: {str(e)}")
    
    if deletion_errors:
        return {"error": "Partial deletion failure", "details": deletion_errors}
    
    return {"success": True, "message": "Account deleted"}


# =============================================================================
# SHARED RESULTS
# =============================================================================

# In-memory store for shared results (consider moving to database)
_shared_results = {}


def store_shared_result(share_id, data, ttl_hours=72):
    """Store a shared result."""
    import time
    _shared_results[share_id] = {
        "data": data,
        "expires": time.time() + (ttl_hours * 3600)
    }
    return {"success": True}


def get_shared_result(share_id):
    """Get a shared result."""
    import time
    if share_id not in _shared_results:
        return None
    
    result = _shared_results[share_id]
    if time.time() > result["expires"]:
        del _shared_results[share_id]
        return None
    
    return result["data"]