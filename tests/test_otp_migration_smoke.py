"""Smoke test for otp migration parser (synthetic GA export)."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from otp.migration import parse_migration_uri  # noqa: E402
from otp.totp import current_code  # noqa: E402


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field_bytes(num: int, data: bytes) -> bytes:
    return _varint((num << 3) | 2) + _varint(len(data)) + data


def _field_varint(num: int, val: int) -> bytes:
    return _varint((num << 3) | 0) + _varint(val)


class OtpMigrationSmokeTest(unittest.TestCase):
    def test_parse_and_code(self) -> None:
        secret = b"Hello!"
        otp = b"".join(
            [
                _field_bytes(1, secret),
                _field_bytes(2, b"demo"),
                _field_bytes(3, b"GitHub"),
                _field_varint(4, 1),
                _field_varint(5, 1),
                _field_varint(6, 2),
            ]
        )
        payload = (
            _field_bytes(1, otp)
            + _field_varint(2, 1)
            + _field_varint(3, 1)
            + _field_varint(4, 0)
        )
        uri = "otpauth-migration://offline?data=" + quote(
            base64.b64encode(payload).decode()
        )
        accounts = parse_migration_uri(uri)
        self.assertEqual(len(accounts), 1)
        acc = accounts[0]
        self.assertEqual(acc.issuer, "GitHub")
        self.assertEqual(acc.name, "demo")
        code = current_code(acc)
        self.assertTrue(code.isdigit() and len(code) == 6)
        import pyotp

        self.assertEqual(pyotp.TOTP(acc.secret_b32).now(), code)


if __name__ == "__main__":
    unittest.main()
