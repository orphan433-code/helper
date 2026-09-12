"""Курсы Activ с главной: USD / EUR, покупка и продажа."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from device.ocr import OcrHit
from ui.job_control import raise_if_stopped

_NUM_RE = re.compile(
    r"^[\$€]?\s*(\d{1,3}(?:[.,]\d{1,4})?|\d+)\s*$"
)
_EUR_RANGE = (8.0, 20.0)
_USD_RANGE = (6.0, 15.0)
_RUB_RANGE = (0.04, 0.3)


@dataclass(frozen=True)
class ActivRates:
    usd_buy: float
    usd_sell: float
    eur_buy: float
    eur_sell: float
    rub_buy: float = 0.0
    rub_sell: float = 0.0

    def tjs_for_eur(self, eur: float) -> float:
        return _money2(eur * self.eur_sell)

    def tjs_for_usd(self, usd: float) -> float:
        return _money2(usd * self.usd_sell)

    def confirm_prompt(self) -> str:
        return (
            "EZE курс Activ\n"
            f"EUR продажа {self.eur_sell:g}\n"
            f"USD продажа {self.usd_sell:g}\n"
            f"EUR покупка {self.eur_buy:g}\n"
            f"USD покупка {self.usd_buy:g}\n"
            f"В банк: 1 EUR = {self.eur_sell:g} TJS"
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "usd_buy": self.usd_buy,
            "usd_sell": self.usd_sell,
            "eur_buy": self.eur_buy,
            "eur_sell": self.eur_sell,
            "rub_buy": self.rub_buy,
            "rub_sell": self.rub_sell,
        }


def _money2(value: float) -> float:
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_rate_number(text: str) -> float | None:
    raw = (text or "").strip().replace("\xa0", "").replace(" ", "")
    raw = raw.replace("−", "-")
    if not raw or any(ch.isalpha() for ch in raw):
        return None
    m = _NUM_RE.match(raw)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _label_code(text: str) -> str | None:
    hay = (text or "").strip().upper().replace("−", "-")
    hay = hay.replace("—", "-")
    if any(ch.isdigit() for ch in hay):
        return None
    if "EUR" in hay:
        return "EUR"
    if "USD" in hay:
        return "USD"
    if "RUB" in hay:
        return "RUB"
    return None


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _nearest_label(
    hit: OcrHit,
    labels: dict[str, OcrHit],
) -> str | None:
    best: str | None = None
    best_dx = 1e9
    for code, label in labels.items():
        dy = abs(hit.y - label.y)
        if dy > 55:
            continue
        dx = hit.x - label.x
        if dx < -20:
            continue
        if dx > 180:
            continue
        if dx < best_dx:
            best_dx = dx
            best = code
    return best


def _pair_from_column(
    column: list[tuple[float, OcrHit]],
    bounds: tuple[float, float],
) -> tuple[float, float] | None:
    in_range = [(value, hit) for value, hit in column if _in_range(value, bounds)]
    if len(in_range) < 2:
        in_range = list(column)
    if len(in_range) < 2:
        return None
    in_range.sort(key=lambda item: item[1].y)
    buy = in_range[0][0]
    sell = in_range[-1][0]
    if sell < buy:
        buy, sell = sell, buy
    if buy <= 0 or sell <= 0:
        return None
    return buy, sell


def parse_activ_home_rates(hits: list[OcrHit]) -> ActivRates | None:
    """Главная Activ: три чипа RUB / USD / EUR, сверху покупка, снизу продажа."""
    labels: dict[str, OcrHit] = {}
    numbers: list[tuple[float, OcrHit]] = []
    for hit in hits:
        code = _label_code(hit.text)
        if code and code not in labels:
            labels[code] = hit
            continue
        value = parse_rate_number(hit.text)
        if value is not None:
            numbers.append((value, hit))

    usd_hit = labels.get("USD")
    eur_hit = labels.get("EUR")
    if usd_hit is None or eur_hit is None:
        return None

    columns: dict[str, list[tuple[float, OcrHit]]] = {
        code: [] for code in labels
    }
    for value, hit in numbers:
        owner = _nearest_label(hit, labels)
        if owner is not None:
            columns[owner].append((value, hit))

    usd = _pair_from_column(columns.get("USD", []), _USD_RANGE)
    eur = _pair_from_column(columns.get("EUR", []), _EUR_RANGE)
    if usd is None or eur is None:
        return None
    rub = (0.0, 0.0)
    if "RUB" in columns:
        found = _pair_from_column(columns["RUB"], _RUB_RANGE)
        if found is not None:
            rub = found
    return ActivRates(
        usd_buy=usd[0],
        usd_sell=usd[1],
        eur_buy=eur[0],
        eur_sell=eur[1],
        rub_buy=rub[0],
        rub_sell=rub[1],
    )


def looks_like_activ_home(hits: list[OcrHit]) -> bool:
    texts = " ".join(h.text.lower() for h in hits)
    return "главн" in texts or "платеж" in texts or "activ" in texts


def wait_for_activ_rates(
    *,
    timeout_sec: float = 180.0,
    poll_sec: float = 1.2,
) -> ActivRates:
    from bank.screen import scan_screen

    deadline = time.monotonic() + max(15.0, float(timeout_sec))
    poll = max(0.4, float(poll_sec))
    while time.monotonic() < deadline:
        raise_if_stopped()
        try:
            hits = scan_screen()
        except Exception:
            time.sleep(poll)
            continue
        rates = parse_activ_home_rates(hits)
        if rates is not None:
            return rates
        time.sleep(poll)
    raise TimeoutError("не увидел курсы USD/EUR на главной Activ")
