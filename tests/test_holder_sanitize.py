"""Очистка ФИО перед вводом в Activ."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.validators import sanitize_holder_name_for_bank  # noqa: E402


class HolderPlusTests(unittest.TestCase):
    def test_trailing_and_inner_plus(self) -> None:
        self.assertEqual(
            sanitize_holder_name_for_bank("LAKHVANOVA+AIDE+"),
            "LAKHANOVA AIDE",
        )

    def test_url_encoded_plus(self) -> None:
        self.assertEqual(
            sanitize_holder_name_for_bank("LAKHVANOVA%2BAIDE%2B"),
            "LAKHANOVA AIDE",
        )

    def test_underscores_and_slashes(self) -> None:
        self.assertEqual(
            sanitize_holder_name_for_bank("IVAN_PETROV/SIDOR"),
            "IVAN PETROV SIDOR",
        )

    def test_plain_name_unchanged_rules(self) -> None:
        self.assertEqual(
            sanitize_holder_name_for_bank("IVAN PETROV"),
            "IVAN PETROV",
        )


if __name__ == "__main__":
    unittest.main()
