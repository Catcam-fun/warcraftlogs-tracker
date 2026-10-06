"""
origin.py - Is this request from our CloudFront distribution?

On AWS the Lambda function URL is public, so CloudFront adds a secret header
(X-Origin-Verify) to every request it forwards, and the function only serves
requests that carry it. ORIGIN_VERIFY_SECRET unset (local dev) means no
such lock.
"""

import hmac
import os

from flask import request

HEADER = 'X-Origin-Verify'


def secret():
    return os.environ.get('ORIGIN_VERIFY_SECRET') or ''


def from_cloudfront():
    expected = secret()
    sent = request.headers.get(HEADER, '')
    return bool(expected) and hmac.compare_digest(sent.encode(), expected.encode())
