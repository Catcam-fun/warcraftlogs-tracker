"""
user_errors.py - What a visitor is told when an analysis can't run.

The details of a failure (addresses, status codes, raw API messages) go to the
server log only. The visitor gets a short, plain explanation of what went
wrong and what to try.
"""

SIGN_IN_REJECTED = ("WarcraftLogs didn't accept your Client ID and Secret. Check them on your "
                    "WarcraftLogs API Clients page and try again.")
BUSY = "WarcraftLogs is limiting requests right now. Wait a minute and try again."
DOWN = ("WarcraftLogs isn't responding right now (it may be down for maintenance). "
        "Please try again in a little while.")
NO_GUILD = "WarcraftLogs couldn't find that guild. Check the guild name, server and region."
SIGN_IN_FAILED = "Couldn't sign in to WarcraftLogs. Please try again in a little while."
SIGN_IN_LOST = "WarcraftLogs stopped accepting the sign-in partway through. Please run the analysis again."
ANALYSIS_FAILED = "Something went wrong while reading these logs. Please try again in a little while."


class UpstreamError(Exception):
    """A request to WarcraftLogs failed. `status` is the HTTP status, or None
    when no answer came back (timeout, connection error)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _chain(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _upstream_status(exc):
    """(found, status) for the first UpstreamError behind exc."""
    for e in _chain(exc):
        if isinstance(e, UpstreamError):
            return True, e.status
    return False, None


def for_sign_in(exc):
    """Message for a failed WarcraftLogs sign-in (get_access_token)."""
    found, status = _upstream_status(exc)
    if found:
        if status in (400, 401, 403):
            return SIGN_IN_REJECTED
        if status == 429:
            return BUSY
        if status is None or status >= 500:
            return DOWN
    return SIGN_IN_FAILED


def for_analysis(exc):
    """Message for anything else that stops an analysis."""
    if any("No guild exists" in str(e) for e in _chain(exc)):
        return NO_GUILD
    found, status = _upstream_status(exc)
    if found:
        if status == 429:
            return BUSY
        if status is None or status >= 500:
            return DOWN
        if status in (401, 403):
            return SIGN_IN_LOST
    return ANALYSIS_FAILED
