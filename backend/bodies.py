"""
bodies.py - Read a JSON request body that may be gzip-compressed.

Shares and saves send a whole analysis, which for a big guild is many MB of
JSON. Lambda refuses request bodies over 6 MB, so the site gzips them
(Content-Encoding: gzip, roughly 10x smaller). Plain JSON still works.
"""

import json
import zlib

from flask import request

# Largest analysis accepted once decompressed (stored compressed, it must
# still fit the saved/share limits in supabase_client).
MAX_JSON_BYTES = 64 * 1024 * 1024


class BodyTooLarge(Exception):
    pass


def json_body(max_bytes=MAX_JSON_BYTES):
    """The request's JSON, or None if it isn't valid JSON. Raises BodyTooLarge."""
    raw = request.get_data(cache=False)
    if request.headers.get('Content-Encoding', '').strip().lower() == 'gzip':
        try:
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)    # gzip framing
            raw = inflater.decompress(raw, max_bytes + 1)
        except zlib.error:
            return None
        if len(raw) > max_bytes or inflater.unconsumed_tail:
            raise BodyTooLarge()
    elif len(raw) > max_bytes:
        raise BodyTooLarge()
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
