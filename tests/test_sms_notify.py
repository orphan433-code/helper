"""Разбор OTP из шторки: Life / ActivBank, не только «Код:»."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notify.sms import _pkg_allowed, extract_code  # noqa: E402


class SmsCodeExtractTests(unittest.TestCase):
    def test_classic_ru(self) -> None:
        self.assertEqual(
            extract_code({"title": "ActivBank", "text": "Код: 1234"}),
            "1234",
        )

    def test_confirmation_phrase(self) -> None:
        self.assertEqual(
            extract_code(
                {"title": "ActivBank", "text": "Код подтверждения: 567890"}
            ),
            "567890",
        )

    def test_latin_kod(self) -> None:
        self.assertEqual(
            extract_code({"title": "ActivBank", "text": "Kod: 4321"}),
            "4321",
        )

    def test_latin_phrase(self) -> None:
        self.assertEqual(
            extract_code(
                {
                    "title": "ActivBank",
                    "text": "Kod podtverzhdeniya 9999",
                }
            ),
            "9999",
        )

    def test_bare_digits_activ(self) -> None:
        self.assertEqual(
            extract_code({"title": "ActivBank", "text": "2468", "pkg": "tj.life.mobile.app"}),
            "2468",
        )

    def test_spisanie_not_code(self) -> None:
        self.assertIsNone(
            extract_code(
                {
                    "title": "ActivBank",
                    "text": "Spisanie so scheta Karta ***3595 Summa 1549.25 TJS",
                    "pkg": "tj.life.mobile.app",
                }
            )
        )

    def test_pkg_filter_life(self) -> None:
        self.assertTrue(_pkg_allowed("tj.life.mobile.app", None))
        self.assertTrue(_pkg_allowed("tj.life.mobile.app", "life,polyphone"))
        self.assertFalse(_pkg_allowed("tj.life.mobile.app", "polyphone"))


if __name__ == "__main__":
    unittest.main()
