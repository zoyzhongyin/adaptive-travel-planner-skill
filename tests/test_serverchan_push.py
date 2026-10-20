"""Offline-only tests for secret-safe ServerChan Turbo notification transport."""
import io
import unittest
from unittest.mock import patch

from scripts.serverchan_push import DeliveryError, send_wechat


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.buffer = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, length):
        return self.buffer.read(length)


class ServerChanPushTests(unittest.TestCase):
    def test_invalid_key_stops_before_network(self):
        with patch("scripts.serverchan_push.urlopen") as mocked:
            with self.assertRaises(DeliveryError) as seen:
                send_wechat("wrong-key", "hello", "body")
            self.assertEqual(str(seen.exception), "missing_or_invalid_turbo_sendkey")
            mocked.assert_not_called()

    def test_success_response(self):
        with patch("scripts.serverchan_push.urlopen", return_value=FakeResponse(b'{"code":0,"data":{"pushid":"test"}}')) as mocked:
            send_wechat("SCT123ABC", "ticket update", "Price fell")
            sent_request = mocked.call_args.args[0]
            self.assertIn(b"title=ticket+update", sent_request.data)
            self.assertIn(b"desp=Price+fell", sent_request.data)

    def test_api_denial_is_safe_and_no_secret_in_logs(self):
        key = "SCTPRIVATE123"
        with patch("scripts.serverchan_push.urlopen", return_value=FakeResponse(b'{"code":429,"message":"token SCTPRIVATE123"}')):
            with self.assertRaises(DeliveryError) as seen:
                send_wechat(key, "hello", "body")
        self.assertEqual(str(seen.exception), "server_response_not_successful")
        self.assertNotIn(key, str(seen.exception))


if __name__ == "__main__":
    unittest.main()
