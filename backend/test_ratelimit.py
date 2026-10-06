import os
import unittest
from unittest import mock

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


class CloudFrontClientIpTests(unittest.TestCase):
    """Behind CloudFront (AWS), requests that carry the origin secret come from CloudFront."""

    def ip(self, headers, remote="127.0.0.1"):
        with mock.patch.dict(os.environ, {"ORIGIN_VERIFY_SECRET": "s3cret"}), \
                app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": remote}):
            return client_ip()

    def test_uses_the_viewer_ip_cloudfront_wrote(self):
        self.assertEqual(self.ip({"X-Origin-Verify": "s3cret", "X-Viewer-Ip": "203.0.113.7"}), "203.0.113.7")
        self.assertEqual(self.ip({"X-Origin-Verify": "s3cret", "X-Viewer-Ip": "2001:db8::17"}), "2001:db8::17")

    def test_viewer_ip_without_the_secret_is_ignored(self):
        self.assertEqual(self.ip({"X-Viewer-Ip": "203.0.113.7"}), "127.0.0.1")
        self.assertEqual(self.ip({"X-Origin-Verify": "wrong", "X-Viewer-Ip": "203.0.113.7"}), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
