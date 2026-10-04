import unittest

from flask import Flask

from ratelimit import client_ip

app = Flask(__name__)


class ClientIpTests(unittest.TestCase):
    def ip(self, headers, remote="10.0.0.1"):
        with app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": remote}):
            return client_ip()

    def test_uses_cloudflare_connecting_ip(self):
        self.assertEqual(self.ip({"CF-Connecting-IP": "203.0.113.7"}), "203.0.113.7")

    def test_forged_forwarded_for_does_not_change_the_key(self):
        # Render appends to a client-sent X-Forwarded-For instead of replacing it.
        for forged in ("1.1.1.1", "2.2.2.2, 198.51.100.4"):
            with self.subTest(forged=forged):
                self.assertEqual(
                    self.ip({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": forged}),
                    "203.0.113.7",
                )

    def test_without_cloudflare_uses_the_connection_address(self):
        self.assertEqual(self.ip({"X-Forwarded-For": "1.1.1.1"}, remote="127.0.0.1"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
