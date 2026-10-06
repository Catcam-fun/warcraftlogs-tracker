"""
streaming.py - Keep a long server-sent-events stream alive while it's quiet.

An analysis can go a minute or more without a progress message (a big
WarcraftLogs report). Proxies in front of the API (CloudFront's origin read
timeout, Cloudflare's) close a response that sends nothing for too long, so
the stream gets an SSE comment line every few seconds while it's quiet. The
site's stream reader only acts on "data: " lines and ignores comments.
"""

import queue
import threading

KEEPALIVE = ": keepalive\n\n"
_DONE = object()


def with_heartbeat(source, every=15):
    """Yield everything `source` yields, plus KEEPALIVE after `every` quiet seconds.

    `source` runs on its own thread (it must not need the Flask request
    context). If the client goes away, the source stops at its next message.
    An exception in the source is raised here.
    """
    out = queue.Queue()
    stop = threading.Event()

    def run():
        try:
            for item in source:
                if stop.is_set():
                    break
                out.put(("item", item))
        except BaseException as e:      # handed to the consumer
            out.put(("error", e))
        finally:
            close = getattr(source, "close", None)
            if close:
                close()
            out.put(("done", _DONE))

    threading.Thread(target=run, daemon=True).start()
    try:
        while True:
            try:
                kind, value = out.get(timeout=every)
            except queue.Empty:
                yield KEEPALIVE
                continue
            if kind == "item":
                yield value
            elif kind == "error":
                raise value
            else:
                return
    finally:
        stop.set()
