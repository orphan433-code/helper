"""BIN пайплайна + редирект «Уходят», не в отмене."""

from __future__ import annotations

import unittest

from core.bank_bins import EXTRA_REDIRECT_BINS, bins_for
from core.validators import (
    ignored_bank_prefixes,
    session_requisites_key,
    skip_reason_for_card_choice,
    skip_reason_for_ignored_banks,
    skip_reason_for_session_duplicate,
)
from core.decline_bins import DECLINE_BIN_PREFIXES, DECLINE_DEFAULT_ON
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES

_UHODYAT = ("4098", "410170", "537524", "557755")


class UhodyatBinsTests(unittest.TestCase):
    def test_pipeline_keeps_both(self) -> None:
        for bin_code in _UHODYAT:
            self.assertIn(bin_code, PIPELINE_BIN_PREFIXES)

    def test_not_in_decline(self) -> None:
        for bin_code in _UHODYAT:
            self.assertNotIn(bin_code, DECLINE_BIN_PREFIXES)

    def test_in_redirect_extra(self) -> None:
        for bin_code in _UHODYAT:
            self.assertIn(bin_code, EXTRA_REDIRECT_BINS)
            self.assertIn(bin_code, REDIRECT_BIN_PREFIXES)

    def test_pipeline_bins_whitelist_when_on(self) -> None:
        from core.validators import skip_reason_for_card_bin

        self.assertIsNone(
            skip_reason_for_card_bin("537524******1111", ["537524"]),
        )
        self.assertEqual(
            skip_reason_for_card_bin("4125702044961830", ["537524", "557755"]),
            "BIN не из 537524, 557755",
        )
        self.assertIsNone(skip_reason_for_card_bin("537524******1111", []))
        self.assertIsNone(
            skip_reason_for_card_bin("4098123456789012", ["4098", "410170"]),
        )
        self.assertIsNone(
            skip_reason_for_card_bin("410170******9999", ["410170"]),
        )

    def test_bin_whitelist_beats_visa_only_brand(self) -> None:
        """Visa вкл / MC выкл не режет 537524/557755 если BIN выбран."""
        self.assertIsNone(
            skip_reason_for_card_choice(
                "537524******1111",
                allow_visa=True,
                allow_mastercard=False,
                bin_prefixes=["537524", "557755"],
            )
        )
        self.assertIsNone(
            skip_reason_for_card_choice(
                "557755******0000",
                allow_visa=True,
                allow_mastercard=False,
                bin_prefixes=["537524", "557755"],
            )
        )
        self.assertEqual(
            skip_reason_for_card_choice(
                "4125702044961830",
                allow_visa=True,
                allow_mastercard=False,
                bin_prefixes=["537524", "557755"],
            ),
            "BIN не из 537524, 557755",
        )
        self.assertEqual(
            skip_reason_for_card_choice(
                "537524******1111",
                allow_visa=True,
                allow_mastercard=False,
                bin_prefixes=None,
            ),
            "MC (5…) выключена",
        )

    def test_liberty_mc_without_537524(self) -> None:
        self.assertNotIn("537524", bins_for("liberty", mastercard=True))
        self.assertIn("532434", bins_for("liberty", mastercard=True))


class IgnoredBankSkipTests(unittest.TestCase):
    def test_tbc_all_bins(self) -> None:
        self.assertEqual(
            ignored_bank_prefixes("tbc"),
            bins_for("tbc"),
        )
        self.assertIn("431571", ignored_bank_prefixes("tbc"))
        self.assertIn("516185", ignored_bank_prefixes("tbc"))
        for bin_code in ("515881", "535661", "559656"):
            self.assertIn(bin_code, bins_for("tbc"))
            self.assertIn(bin_code, ignored_bank_prefixes("tbc"))
            self.assertIn(bin_code, REDIRECT_BIN_PREFIXES)
            self.assertIn(bin_code, DECLINE_BIN_PREFIXES)
            self.assertIn(bin_code, DECLINE_DEFAULT_ON)

    def test_bog_all_bins(self) -> None:
        self.assertEqual(
            ignored_bank_prefixes("bog"),
            bins_for("bog"),
        )
        self.assertIn("411634", ignored_bank_prefixes("bog"))
        self.assertIn("548888", ignored_bank_prefixes("bog"))

    def test_skip_tbc_visa_and_mc(self) -> None:
        self.assertEqual(
            skip_reason_for_ignored_banks("431571******1234", skip_tbc=True),
            "TBC (431571…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("516185******1111", skip_tbc=True),
            "TBC (516185…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("535661******9784", skip_tbc=True),
            "TBC (535661…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("515881******0015", skip_tbc=True),
            "TBC (515881…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("559656******2251", skip_tbc=True),
            "TBC (559656…)",
        )

    def test_skip_bog_visa_and_mc(self) -> None:
        self.assertEqual(
            skip_reason_for_ignored_banks("411634******7227", skip_bog=True),
            "BOG (411634…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("548888******0000", skip_bog=True),
            "BOG (548888…)",
        )

    def test_skip_tjk(self) -> None:
        self.assertEqual(bins_for("tjk"), ("548028",))
        self.assertIn("548028", ignored_bank_prefixes("tjk"))
        self.assertIn("548028", REDIRECT_BIN_PREFIXES)
        self.assertIn("548028", DECLINE_BIN_PREFIXES)
        self.assertIn("548028", DECLINE_DEFAULT_ON)
        self.assertEqual(
            skip_reason_for_ignored_banks("5480282861252825", skip_tjk=True),
            "ТЖК (548028…)",
        )
        self.assertIsNone(
            skip_reason_for_ignored_banks("5480282861252825", skip_tjk=False)
        )
        self.assertIsNone(
            skip_reason_for_ignored_banks("5480282861252825", skip_tbc=True, skip_bog=True)
        )

    def test_liberty_not_skipped(self) -> None:
        self.assertIsNone(
            skip_reason_for_ignored_banks(
                "4125702044961830", skip_tbc=True, skip_bog=True, skip_tjk=True
            )
        )

    def test_flags_off_allows(self) -> None:
        self.assertIsNone(
            skip_reason_for_ignored_banks("431571******1234", skip_tbc=False)
        )
        self.assertIsNone(
            skip_reason_for_ignored_banks("411634******7227", skip_bog=False)
        )


class SessionDuplicateTests(unittest.TestCase):
    def test_same_card_different_name_is_duplicate(self) -> None:
        card = "4111111111111111"
        first = session_requisites_key(card, "BELIAEVQ TATIANA")
        second = session_requisites_key(card, "BELIAEVA TATIANA")
        self.assertEqual(first, second)
        seen = {first: 1}
        reason = skip_reason_for_session_duplicate(
            card, "BELIAEVA TATIANA", requisites_in_run=seen
        )
        self.assertIsNotNone(reason)
        self.assertIn("#1", reason or "")

    def test_other_card_is_not_duplicate(self) -> None:
        seen = {session_requisites_key("4111111111111111", "ONE"): 1}
        self.assertIsNone(
            skip_reason_for_session_duplicate(
                "4222222222222222", "ONE", requisites_in_run=seen
            )
        )


if __name__ == "__main__":
    unittest.main()
