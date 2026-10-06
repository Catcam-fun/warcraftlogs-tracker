import gzip
import json
import unittest

from flask import Flask

from bodies import BodyTooLarge, json_body

app = Flask(__name__)


class JsonBodyTests(unittest.TestCase):
    """Big results are sent gzip-compressed: Lambda refuses request bodies over 6 MB."""

    def parse(self, data, headers=None, **kw):
        with app.test_request_context("/", method="POST", data=data, headers=headers or {}):
            return json_body(**kw)

    def test_plain_json_still_works(self):
        self.assertEqual(self.parse(b'{"a": 1}', {"Content-Type": "application/json"}), {"a": 1})

    def test_gzip_compressed_json(self):
        body = gzip.compress(json.dumps({"events": {"Bob": [1, 2, 3]}}).encode())
        headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
        self.assertEqual(self.parse(body, headers), {"events": {"Bob": [1, 2, 3]}})

    def test_bad_bodies_give_none(self):
        self.assertIsNone(self.parse(b"not json", {"Content-Type": "application/json"}))
        self.assertIsNone(self.parse(b"not gzip", {"Content-Type": "application/json", "Content-Encoding": "gzip"}))

    def test_a_compressed_body_cannot_expand_past_the_cap(self):
        bomb = gzip.compress(b'{"a": "' + b"x" * 2_000_000 + b'"}')
        with self.assertRaises(BodyTooLarge):
            self.parse(bomb, {"Content-Encoding": "gzip"}, max_bytes=1_000_000)


if __name__ == "__main__":
    unittest.main()
