"""Тесты bank_nav: координаты и выбор «Платежи» без живого Mirroring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bank_nav import (  # noqa: E402
    _nav_cfg,
    find_payments_tab,
    hit_in_region,
    is_payments_tab_active,
    other_countries_edge_tap_xy,
    payments_tab_fallback_hit,
    should_tap_payments_tab,
)
from ocr import OcrHit  # noqa: E402

REGION = (20, 235, 278, 627)


def _hit(
    text: str,
    x: float,
    y: float,
    *,
    confidence: float = 0.9,
) -> OcrHit:
    return OcrHit(text=text, confidence=confidence, x=x, y=y, width=40, height=20)


class PaymentsTabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nav = _nav_cfg()

    def test_prefers_bottom_tab_over_header(self) -> None:
        header = _hit("Платежи", 80, 280, confidence=0.95)
        tab = _hit("Платежи", 120, 820, confidence=0.7)
        picked = find_payments_tab([header, tab], REGION, self.nav)
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertAlmostEqual(picked.y, 820, delta=1)

    def test_hit_in_region_inside(self) -> None:
        hit = _hit("Платежи", 150, 500)
        self.assertTrue(hit_in_region(hit, REGION))

    def test_hit_in_region_outside(self) -> None:
        hit = _hit("Платежи", 5, 100)
        self.assertFalse(hit_in_region(hit, REGION))

    def test_payments_tab_active_when_transfers_in_content(self) -> None:
        hits = [
            _hit("Переводы", 60, 600),
            _hit("Платежи", 120, 820),
        ]
        self.assertTrue(is_payments_tab_active(hits, REGION, self.nav))

    def test_payments_tab_inactive_on_home_bottom_transfers(self) -> None:
        """«Переводы» в нижнем таб-баре (высокий Y) — ещё не контент вкладки."""
        hits = [
            _hit("Переводы", 90, 830),
            _hit("Главная", 30, 830),
        ]
        self.assertFalse(is_payments_tab_active(hits, REGION, self.nav))

    def test_payments_tab_fallback_uses_configured_ratios(self) -> None:
        hit = payments_tab_fallback_hit(REGION, self.nav)

        self.assertAlmostEqual(hit.x, 120.08, places=2)
        self.assertAlmostEqual(hit.y, 818.11, places=2)
        self.assertTrue(hit.inferred)

    def test_always_tap_overrides_apparent_active_tab(self) -> None:
        hits = [_hit("Переводы", 60, 600)]
        self.nav["stage2_always_tap_payments"] = True

        self.assertTrue(should_tap_payments_tab(hits, REGION, self.nav))

    def test_other_countries_edge_tap_stays_inside_mirror(self) -> None:
        transfers = _hit("Переводы", 60, 600)

        x, y = other_countries_edge_tap_xy(transfers, REGION, self.nav)

        self.assertAlmostEqual(x, 297.0, places=1)
        self.assertAlmostEqual(y, 668.0, places=1)
        self.assertLess(x, REGION[0] + REGION[2])


if __name__ == "__main__":
    unittest.main()
