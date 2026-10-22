import testenv  # noqa: F401  (before any backend import)
import json
import unittest
from unittest import mock

import app as app_module
import user_errors as ue
import warcraftlogs
from user_errors import UpstreamError

LEAKY = "Request failed after 3 attempt(s): 500 Server Error for url: https://upstream.example.test/oauth/token"


def wrapped(inner, outer="Failed to get access token"):
    """An exception chained the way warcraftlogs.py chains them."""
    try:
        try:
            raise inner
        except Exception as e:
            raise Exception(f"{outer}: {e}") from e
    except Exception as e:
        return e


class MessageTests(unittest.TestCase):
    def test_sign_in_messages_follow_the_status(self):
        for status, expected in ((401, ue.SIGN_IN_REJECTED), (400, ue.SIGN_IN_REJECTED),
                                 (429, ue.BUSY), (500, ue.DOWN), (503, ue.DOWN), (None, ue.DOWN)):
            with self.subTest(status=status):
                self.assertEqual(ue.for_sign_in(wrapped(UpstreamError(LEAKY, status))), expected)
        self.assertEqual(ue.for_sign_in(ValueError("bug")), ue.SIGN_IN_FAILED)

    def test_analysis_messages(self):
        no_guild = wrapped(Exception("GraphQL errors: [{'message': 'No guild exists for this name/server/region.'}]"),
                           "Failed to fetch guild reports")
        self.assertEqual(ue.for_analysis(no_guild), ue.NO_GUILD)
        self.assertEqual(ue.for_analysis(wrapped(UpstreamError(LEAKY, 502))), ue.DOWN)
        self.assertEqual(ue.for_analysis(wrapped(UpstreamError(LEAKY, 429))), ue.BUSY)
        self.assertEqual(ue.for_analysis(wrapped(UpstreamError(LEAKY, 401))), ue.SIGN_IN_LOST)
        self.assertEqual(ue.for_analysis(KeyError("fights")), ue.ANALYSIS_FAILED)

    def test_request_failures_carry_their_status(self):
        response = mock.Mock(status_code=401, headers={})
        error = warcraftlogs.requests.exceptions.HTTPError("401 Client Error", response=response)
        with mock.patch.object(warcraftlogs.requests, 'post', side_effect=error):
            with self.assertRaises(UpstreamError) as caught:
                warcraftlogs.make_request_with_retry('post', 'https://example.test', max_retries=0)
        self.assertEqual(caught.exception.status, 401)


class NoInfrastructureInTheStreamTests(unittest.TestCase):
    BODY = {"clientId": "id", "clientSecret": "secret", "guildName": "G", "server": "S", "region": "us",
            "selectedRaid": "manaforge", "difficulty": "5", "fightZone": "0", "maxCutoff": 5}

    def stream_errors(self):
        raw = app_module.app.test_client().post('/api/analyze', json=self.BODY).get_data(as_text=True)
        return [json.loads(c[5:])["error"] for c in raw.split("\n\n")
                if c.strip().startswith("data:") and '"error"' in c]

    def assert_clean(self, errors, expected):
        self.assertEqual(errors, [expected])
        for text in errors:
            self.assertNotIn("http", text)
            self.assertNotIn("example.test", text)

    def test_a_failed_sign_in_shows_a_plain_message(self):
        with mock.patch.object(app_module, 'get_access_token',
                               side_effect=wrapped(UpstreamError(LEAKY, None))):
            self.assert_clean(self.stream_errors(), ue.DOWN)

    def test_a_failure_later_on_shows_a_plain_message(self):
        with mock.patch.object(app_module, 'get_access_token', return_value='t'), \
                mock.patch.object(app_module, 'get_guild_roster', return_value=set()), \
                mock.patch.object(app_module, 'get_guild_reports',
                                  side_effect=wrapped(UpstreamError(LEAKY, 503), "Failed to fetch guild reports")):
            self.assert_clean(self.stream_errors(), ue.DOWN)


if __name__ == '__main__':
    unittest.main()
