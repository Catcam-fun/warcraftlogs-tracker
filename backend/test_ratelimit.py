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

    def test_client_set_headers_do_not_change_the_key(self):
        for headers in ({"X-Forwarded-For": "1.1.1.1"}, {"X-Forwarded-For": "2.2.2.2, 198.51.100.4"},
                        {"CF-Connecting-IP": "203.0.113.7"}, {"X-Viewer-Ip": "203.0.113.7"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.ip(headers, remote="127.0.0.1"), "127.0.0.1")


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
