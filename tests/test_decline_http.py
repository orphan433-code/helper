"""HTTP отмены: таймаут не роняет скрипт traceback-ом."""

from __future__ import annotations

import unittest
from email.message import Message
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from platcore.api_client import retryable_http_exc, urlopen_read
from ui.web import decline_crash_detail


def _http_error(code: int) -> HTTPError:
    return HTTPError("http://x", code, "x", Message(), BytesIO())


class RetryableHttpTests(unittest.TestCase):
    def test_timeout_error(self) -> None:
        self.assertTrue(retryable_http_exc(TimeoutError("The read operation timed out")))

    def test_urlerror_timed_out(self) -> None:
        self.assertTrue(retryable_http_exc(URLError("timed out")))

    def test_http_503(self) -> None:
        self.assertTrue(retryable_http_exc(_http_error(503)))

    def test_http_400_not_retryable(self) -> None:
        self.assertFalse(retryable_http_exc(_http_error(400)))


class UrlopenReadTests(unittest.TestCase):
    def test_retries_then_raises_timeout(self) -> None:
        req = MagicMock()
        with (
            patch("platcore.api_client.time.sleep") as sleep,
            patch(
                "platcore.api_client.urllib.request.urlopen",
                side_effect=TimeoutError("The read operation timed out"),
            ),
        ):
            with self.assertRaises(TimeoutError) as ctx:
                urlopen_read(req, timeout=60, retries=3)
        self.assertIn("сервер не ответил", str(ctx.exception))
        self.assertEqual(sleep.call_count, 2)

    def test_success_after_timeout(self) -> None:
        req = MagicMock()
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"ok":true}'
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with (
            patch("platcore.api_client.time.sleep"),
            patch(
                "platcore.api_client.urllib.request.urlopen",
                side_effect=[TimeoutError("The read operation timed out"), resp],
            ),
        ):
            status, raw = urlopen_read(req, timeout=60, retries=3)
        self.assertEqual(status, 200)
        self.assertEqual(raw, b'{"ok":true}')


class CrashDetailTests(unittest.TestCase):
    def test_timeout_hides_traceback(self) -> None:
        detail = decline_crash_detail(
            [
                "Traceback (most recent call last):",
                '  File "decline_by_bank_api.py", line 435, in _http_json',
                "TimeoutError: The read operation timed out",
            ]
        )
        self.assertEqual(detail, " — сервер не ответил (таймаут)")


if __name__ == "__main__":
    unittest.main()
