"""Парсер курсов с главной Activ."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bank.activ_rates import parse_activ_home_rates, parse_rate_number  # noqa: E402
from device.ocr import OcrHit, vision_bbox_to_pyautogui  # noqa: E402

_W, _H = 457, 1024


def _hit(text: str, x: float, y: float) -> OcrHit:
    return OcrHit(text, 0.9, x, y, 40, 16)


def _from_vision(text: str, bbox: tuple[float, float, float, float], conf: float = 1.0) -> OcrHit:
    x, y, w, h = vision_bbox_to_pyautogui(
        bbox, image_width=_W, image_height=_H
    )
    return OcrHit(text, conf, x, y, w, h)


class ParseRateNumberTests(unittest.TestCase):
    def test_dot_and_comma(self) -> None:
        self.assertEqual(parse_rate_number("10.81"), 10.81)
        self.assertEqual(parse_rate_number("9,27"), 9.27)
        self.assertIsNone(parse_rate_number("0,00 EUR"))
        self.assertIsNone(parse_rate_number("EUR"))


class ParseActivHomeRatesTests(unittest.TestCase):
    def test_screenshot_vision_layout(self) -> None:
        hits = [
            _from_vision("0,52 USD", (0.257, 0.722, 0.153, 0.017), 0.5),
            _from_vision("0,00 EUR", (0.454, 0.725, 0.162, 0.012)),
            _from_vision("- RUB", (0.066, 0.387, 0.144, 0.025), 0.5),
            _from_vision("0.109", (0.209, 0.402, 0.101, 0.016)),
            _from_vision("0.1112", (0.223, 0.383, 0.092, 0.016)),
            _from_vision("- USD", (0.384, 0.391, 0.131, 0.02), 0.3),
            _from_vision("9.2", (0.528, 0.402, 0.057, 0.016)),
            _from_vision("9.27", (0.528, 0.383, 0.079, 0.016)),
            _from_vision("EUR", (0.725, 0.394, 0.083, 0.014), 0.5),
            _from_vision("10.6", (0.817, 0.402, 0.074, 0.016)),
            _from_vision("10.81", (0.817, 0.383, 0.087, 0.016)),
            _from_vision("Главная", (0.057, 0.07, 0.14, 0.014)),
            _from_vision("Платежи", (0.301, 0.07, 0.149, 0.015)),
        ]
        rates = parse_activ_home_rates(hits)
        self.assertIsNotNone(rates)
        assert rates is not None
        self.assertEqual(rates.usd_buy, 9.2)
        self.assertEqual(rates.usd_sell, 9.27)
        self.assertEqual(rates.eur_buy, 10.6)
        self.assertEqual(rates.eur_sell, 10.81)
        self.assertAlmostEqual(rates.tjs_for_eur(139.73), 1510.48)

    def test_synthetic_top_origin(self) -> None:
        hits = [
            _hit("USD", 180, 640),
            _hit("9.2", 230, 630),
            _hit("9.27", 230, 655),
            _hit("EUR", 320, 640),
            _hit("10.6", 370, 630),
            _hit("10.81", 370, 655),
        ]
        rates = parse_activ_home_rates(hits)
        self.assertIsNotNone(rates)
        assert rates is not None
        self.assertEqual((rates.usd_buy, rates.usd_sell), (9.2, 9.27))
        self.assertEqual((rates.eur_buy, rates.eur_sell), (10.6, 10.81))


if __name__ == "__main__":
    unittest.main()
