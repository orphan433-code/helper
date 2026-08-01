"""Проверка OCR-сверки суммы зачисления для разных валют."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bank_form import find_expected_credit_amount_anywhere  # noqa: E402
from ocr import OcrHit  # noqa: E402


def _hit(text: str, x: float, y: float) -> OcrHit:
    return OcrHit(text, 0.9, x, y, 40, 18)


class ExpectedCreditAmountTests(unittest.TestCase):
    def test_joins_split_eur_amount(self) -> None:
        hits = [
            _hit("101,", 80, 710),
            _hit("56", 125, 711),
            _hit("EUR", 220, 710),
        ]

        self.assertEqual(
            find_expected_credit_amount_anywhere(
                hits,
                101.56,
                "EUR",
                0.01,
            ),
            101.56,
        )

    def test_finds_usd_using_deal_currency(self) -> None:
        hits = [
            _hit("117.21", 90, 710),
            _hit("USD", 220, 710),
        ]

        self.assertEqual(
            find_expected_credit_amount_anywhere(
                hits,
                117.21,
                "USD",
                0.01,
            ),
            117.21,
        )

    def test_does_not_accept_other_currency(self) -> None:
        hits = [
            _hit("101,56", 90, 710),
            _hit("TJS", 220, 710),
        ]

        self.assertIsNone(
            find_expected_credit_amount_anywhere(
                hits,
                101.56,
                "EUR",
                0.01,
            )
        )


if __name__ == "__main__":
    unittest.main()
