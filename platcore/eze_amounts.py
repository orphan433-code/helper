"""Суммы EasySend: Visa = net USDT→USD, MC = GEL→EUR (XE) × курс Activ."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bank.activ_rates import ActivRates


def money2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _num(raw: Any) -> float:
    if raw is None or raw is False:
        return 0.0
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(Decimal(text))
    except Exception:
        return 0.0


def card_scheme(account_raw: str) -> str:
    digits = "".join(ch for ch in (account_raw or "") if ch.isdigit())
    if digits.startswith("4"):
        return "visa"
    if digits[:1] in ("2", "5"):
        return "mastercard"
    return ""


def row_usdt(row: dict[str, Any]) -> float:
    out = row.get("out") if isinstance(row.get("out"), dict) else {}
    trader = _num(out.get("trader"))
    if trader > 0:
        return trader
    return _num(row.get("amount"))


def row_fee(row: dict[str, Any]) -> float:
    fees = row.get("fees") if isinstance(row.get("fees"), dict) else {}
    out = row.get("out") if isinstance(row.get("out"), dict) else {}
    return _num(fees.get("exchange")) or _num(out.get("traderProfit"))


def row_fiat_client(row: dict[str, Any]) -> float:
    out = row.get("out") if isinstance(row.get("out"), dict) else {}
    return _num(out.get("client"))


def row_fiat_code(row: dict[str, Any]) -> str:
    to = row.get("currencyTo") if isinstance(row.get("currencyTo"), dict) else {}
    return str(to.get("code") or "").strip().upper()


def visa_usd_net(row: dict[str, Any]) -> float:
    """Visa: (I receive − fee) как USD. USDT ≈ USD."""
    net = money2(row_usdt(row) - row_fee(row))
    if net <= 0:
        raise ValueError("EZE Visa: net USDT ≤ 0")
    return net


def tjs_for_visa(row: dict[str, Any], rates: ActivRates) -> tuple[float, float]:
    usd = visa_usd_net(row)
    return rates.tjs_for_usd(usd), usd


def tjs_for_mc_eur(eur: float, rates: ActivRates) -> tuple[float, float]:
    give = money2(eur)
    if give <= 0:
        raise ValueError("EZE MC: EUR ≤ 0")
    return rates.tjs_for_eur(give), give
