"""
gunicorn.conf.py - picked up automatically when gunicorn starts in backend/.

An analysis is a long-lived streaming (SSE) request. With gunicorn's
default single sync worker, one running analysis blocks every other
request (page data, shares, saves) until it finishes. Threads let one
process serve many requests at once while keeping in-memory state (report
cache, rate limits) shared.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '1'))
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', '16'))
# With gthread the timeout is a worker heartbeat, not a per-request cap,
# so long analyses keep streaming. AWS Lambda sets 0 (off): Lambda freezes
# the server between requests, and a stale heartbeat after a pause would get
# a healthy worker killed. Lambda's own time limit covers a stuck request.
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5
