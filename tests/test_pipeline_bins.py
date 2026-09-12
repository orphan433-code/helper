"""537524 / 557755: пайплайн + редирект «Уходят», не в отмене."""

from __future__ import annotations

import unittest

from core.bank_bins import EXTRA_REDIRECT_BINS, bins_for
from core.validators import ignored_bank_prefixes, skip_reason_for_ignored_banks
from core.decline_bins import DECLINE_BIN_PREFIXES
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES

_UHODYAT = ("537524", "557755")


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

    def test_skip_bog_visa_and_mc(self) -> None:
        self.assertEqual(
            skip_reason_for_ignored_banks("411634******7227", skip_bog=True),
            "BOG (411634…)",
        )
        self.assertEqual(
            skip_reason_for_ignored_banks("548888******0000", skip_bog=True),
            "BOG (548888…)",
        )

    def test_liberty_not_skipped(self) -> None:
        self.assertIsNone(
            skip_reason_for_ignored_banks(
                "4125702044961830", skip_tbc=True, skip_bog=True
            )
        )

    def test_flags_off_allows(self) -> None:
        self.assertIsNone(
            skip_reason_for_ignored_banks("431571******1234", skip_tbc=False)
        )
        self.assertIsNone(
            skip_reason_for_ignored_banks("411634******7227", skip_bog=False)
        )


if __name__ == "__main__":
    unittest.main()
