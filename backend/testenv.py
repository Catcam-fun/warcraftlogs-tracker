"""
testenv.py - Keeps the backend tests away from the real Supabase.

Test files import this before app, auth, supabase_client or checks. Those
call load_dotenv(), which would pick up a local backend/.env with real keys;
load_dotenv() never overrides a variable that is already set, so blanking
these first leaves storage, the shared report cache and sign-in checks off,
exactly as in GitHub Actions (which has no .env).
"""

import os

for _name in ('SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
    os.environ[_name] = ''
