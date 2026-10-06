import os
import unittest
from unittest import mock

import app as app_module


class OriginLockTests(unittest.TestCase):
    """On AWS the Lambda URL is public; only CloudFront knows the origin secret."""

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_without_a_secret_configured_everything_is_open(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORIGIN_VERIFY_SECRET", None)
            self.assertEqual(self.client.get("/api/health").status_code, 200)
            self.assertEqual(self.client.get("/api/shared/abcdefghijkl").status_code, 404)

    def test_requests_without_the_secret_are_refused(self):
        with mock.patch.dict(os.environ, {"ORIGIN_VERIFY_SECRET": "s3cret"}):
            self.assertEqual(self.client.get("/api/shared/abcdefghijkl").status_code, 403)
            self.assertEqual(self.client.post("/api/analyze", json={}).status_code, 403)
            self.assertEqual(self.client.get("/api/shared/abcdefghijkl",
                                             headers={"X-Origin-Verify": "nope"}).status_code, 403)
            self.assertEqual(self.client.get("/api/shared/abcdefghijkl",
                                             headers={"X-Origin-Verify": "s3cret"}).status_code, 404)

    def test_adapter_health_check_and_warm_ping_stay_open(self):
        # The Lambda Web Adapter calls these itself, from inside the function.
        with mock.patch.dict(os.environ, {"ORIGIN_VERIFY_SECRET": "s3cret"}):
            self.assertEqual(self.client.get("/api/health").status_code, 200)
            self.assertEqual(self.client.post("/events", json={"source": "aws.events"}).status_code, 204)


if __name__ == "__main__":
    unittest.main()
