"""Фильтр валюты / USDT перед Accept."""

from __future__ import annotations

import unittest

from core.pipeline_currencies import (
    fiat_code_from_amount_raw,
    gui_pipeline_currencies,
    normalize_pipeline_currencies,
    skip_reason_for_currency,
)
from platcore.api_accept import _row_usdt, _skip_row


class CurrencyFilterTests(unittest.TestCase):
    def test_empty_means_all(self) -> None:
        self.assertIsNone(skip_reason_for_currency("THB", []))
        self.assertIsNone(skip_reason_for_currency("EUR", None))

    def test_skips_other_code(self) -> None:
        reason = skip_reason_for_currency("TRY", ["EUR", "THB"])
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("TRY", reason)

    def test_allows_selected(self) -> None:
        self.assertIsNone(skip_reason_for_currency("eur", ["EUR", "THB"]))

    def test_gui_keeps_known_order(self) -> None:
        self.assertEqual(
            gui_pipeline_currencies(["try", "EUR", "XXX", "THB"]),
            ["EUR", "THB", "TRY"],
        )

    def test_normalize_keeps_alpha3(self) -> None:
        self.assertEqual(
            normalize_pipeline_currencies("eur, gel"),
            ["EUR", "GEL"],
        )

    def test_gel_not_in_hz_filter(self) -> None:
        self.assertIsNotNone(skip_reason_for_currency("GEL", ["EUR", "THB", "TRY"]))
        self.assertIsNone(skip_reason_for_currency("GEL", ["GEL"]))

    def test_fiat_from_preview_amount(self) -> None:
        self.assertEqual(fiat_code_from_amount_raw("12 450 THB"), "THB")
        self.assertEqual(fiat_code_from_amount_raw(""), "")

    def test_ledger_allows_gel(self) -> None:
        from platcore.api_accept import _deal_from_ledger

        row = {
            "_id": "abc",
            "orderId": "O1",
            "out": {"client": 100},
            "currencyTo": {"code": "GEL"},
            "bank": {"name": "x"},
        }
        buy = {
            "credentials": {
                "accountNumber": "4111111111111111",
                "ownerName": "A B",
            },
            "out": {"client": 100},
            "currencyTo": {"code": "GEL"},
        }
        ledger = {
            "tjs": "1000.00",
            "give_amt": "100.00",
            "give_cur": "gel",
            "deal_id": "O1",
        }
        deal, _tjs, _give, give_cur = _deal_from_ledger(
            row=row, buy=buy, ledger=ledger
        )
        self.assertEqual(give_cur, "GEL")
        self.assertEqual(deal.amount_eur, 0.0)
        self.assertEqual(deal.amount_usd, 0.0)
        self.assertAlmostEqual(deal.amount_tjs, 1000.0)


class UsdtFilterFieldTests(unittest.TestCase):
    def test_prefers_out_trader_over_merchant_amount(self) -> None:
        row = {
            "amount": 1507.15,
            "out": {"trader": 1450.789, "client": 1210},
            "currencyTo": {"code": "EUR"},
            "credentials": {
                "accountNumber": "5431570000114603",
                "ownerName": "ILIC UROS",
            },
        }
        self.assertAlmostEqual(_row_usdt(row), 1450.789, places=3)
        # По merchant (>1500) резало бы; по trader — нет
        self.assertIsNone(
            _skip_row(
                row,
                min_amount=1.0,
                max_amount=1500.0,
                allow_visa=False,
                allow_mc=True,
                bin_prefixes=None,
                currencies=["EUR", "THB", "TRY"],
                requisites_in_run={},
            )
        )

    def test_fallback_to_amount_without_trader(self) -> None:
        self.assertEqual(_row_usdt({"amount": 100.5}), 100.5)


if __name__ == "__main__":
    unittest.main()
