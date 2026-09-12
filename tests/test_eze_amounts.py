"""Суммы EasySend: Visa net USD, MC EUR × Activ продажа."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bank.activ_rates import ActivRates  # noqa: E402
from platcore.eze_amounts import (  # noqa: E402
    card_scheme,
    tjs_for_mc_eur,
    tjs_for_visa,
    visa_usd_net,
)
from platcore.eze_accept import eze_accept_looks_taken  # noqa: E402
from platcore.eze_xe import parse_xe_eur, xe_rate_parts  # noqa: E402

RATES = ActivRates(
    usd_buy=9.2,
    usd_sell=9.27,
    eur_buy=10.6,
    eur_sell=10.81,
)


class CardSchemeTests(unittest.TestCase):
    def test_visa_mc(self) -> None:
        self.assertEqual(card_scheme("4" + "0" * 15), "visa")
        self.assertEqual(card_scheme("5" + "0" * 15), "mastercard")
        self.assertEqual(card_scheme("2" + "0" * 15), "mastercard")


class VisaAmountsTests(unittest.TestCase):
    def test_net_and_tjs(self) -> None:
        row = {
            "out": {"trader": 100.0, "traderProfit": 3.1946},
            "fees": {"exchange": 3.1946},
            "credentials": {"accountNumber": "4000000000000000"},
        }
        usd = visa_usd_net(row)
        self.assertEqual(usd, 96.81)
        tjs, give = tjs_for_visa(row, RATES)
        self.assertEqual(give, 96.81)
        self.assertEqual(tjs, 897.43)


class McAmountsTests(unittest.TestCase):
    def test_eur_sell_from_screenshot(self) -> None:
        tjs, give = tjs_for_mc_eur(139.73, RATES)
        self.assertEqual(give, 139.73)
        self.assertEqual(tjs, 1510.48)


class XeParseTests(unittest.TestCase):
    def test_ignores_gel_amount(self) -> None:
        text = "421.26 GEL = 139.73 EUR United States Dollar"
        self.assertEqual(parse_xe_eur(text, 421.26), 139.73)

    def test_widget_gel_84_25(self) -> None:
        text = (
            "From 84.25 GEL - Georgian lari  To €27.95 EUR - Euro  "
            "1.00 GEL = 0.33185231 EUR  Mid-market rate at 10:43 UTC"
        )
        self.assertEqual(parse_xe_eur(text, 84.25), 27.95)
        tjs, give = tjs_for_mc_eur(27.95, RATES)
        self.assertEqual(give, 27.95)
        self.assertEqual(tjs, 302.14)

    def test_widget_gel_174_12_ignores_page_50(self) -> None:
        text = (
            "Convert €50  From ₾174.12 GEL - Georgian lari  "
            "To €57.77 EUR - Euro  "
            "1.00 GEL = 0.33181106 EUR  Mid-market rate at 10:54 UTC"
        )
        self.assertEqual(parse_xe_eur(text, 174.12), 57.77)
        tjs, give = tjs_for_mc_eur(57.77, RATES)
        self.assertEqual(give, 57.77)
        self.assertEqual(tjs, 624.49)

    def test_widget_gel_168_50_picks_to_not_short_rate(self) -> None:
        text = (
            "1 GEL = 0.33166 EUR  Convert €55.88  "
            "From ₾168.50 GEL - Georgian Lari  To €55.89 EUR - Euro  "
            "1.00 GEL = 0.33174013 EUR  Mid-market rate at 11:08 UTC"
        )
        self.assertEqual(parse_xe_eur(text, 168.50), 55.89)
        tjs, give = tjs_for_mc_eur(55.89, RATES)
        self.assertEqual(give, 55.89)
        self.assertEqual(tjs, 604.17)

    def test_long_rate_without_to(self) -> None:
        self.assertEqual(
            parse_xe_eur("1.00 GEL = 0.33174013 EUR", 168.50),
            55.89,
        )

    def test_xe_rate_parts_split(self) -> None:
        self.assertEqual(xe_rate_parts(0.33174013), ("0.33", "174013"))
        self.assertEqual(xe_rate_parts(0.33181106), ("0.33", "181106"))

    def test_ignores_fraction_tail_25(self) -> None:
        self.assertIsNone(parse_xe_eur("From 84.25 GEL 25 other", 84.25))


class EzeAcceptLieTests(unittest.TestCase):
    def test_pending_wins(self) -> None:
        self.assertTrue(
            eze_accept_looks_taken(
                "abc", pending_ids={"abc"}, new_ids={"abc"}
            )
        )

    def test_still_in_new(self) -> None:
        self.assertFalse(
            eze_accept_looks_taken("abc", pending_ids=set(), new_ids={"abc"})
        )

    def test_gone_from_new(self) -> None:
        self.assertTrue(
            eze_accept_looks_taken("abc", pending_ids=set(), new_ids=set())
        )


if __name__ == "__main__":
    unittest.main()
