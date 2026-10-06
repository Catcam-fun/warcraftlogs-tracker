import time
import unittest

from streaming import KEEPALIVE, with_heartbeat


class HeartbeatTests(unittest.TestCase):
    def test_passes_every_message_through_in_order(self):
        self.assertEqual(list(with_heartbeat(iter(["a", "b", "c"]), every=5)), ["a", "b", "c"])

    def test_sends_keepalives_while_the_source_is_quiet(self):
        def slow():
            yield "start"
            time.sleep(0.35)          # a long WarcraftLogs fetch with nothing to report
            yield "done"
        out = list(with_heartbeat(slow(), every=0.1))
        self.assertEqual(out[0], "start")
        self.assertEqual(out[-1], "done")
        self.assertGreaterEqual(out.count(KEEPALIVE), 2)
        self.assertTrue(KEEPALIVE.startswith(":"))   # an SSE comment: the site ignores it

    def test_an_error_in_the_source_reaches_the_caller(self):
        def broken():
            yield "a"
            raise RuntimeError("boom")
        out = with_heartbeat(broken(), every=5)
        self.assertEqual(next(out), "a")
        with self.assertRaises(RuntimeError):
            next(out)


if __name__ == "__main__":
    unittest.main()
