"""Модели данных tzk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RowPreview:
    fingerprint: str
    time_text: str
    amount_raw: str  # фиат в списке (THB/GEL/…) — сверки после входа
    account_raw: str
    holder_raw: str
    payment_method: str
    amount_usdt_raw: str = ""  # унифицированная сумма — только фильтр входа


@dataclass(frozen=True)
class TzkDeal:
    task_id: str
    account_raw: str
    account_digits: str
    holder_name: str
    amount_check: float  # You send — сверка со списком (GEL и т.д.)
    amount_check_currency: str
    amount_tjs: float  # Activ to MC — ввод в банк
    amount_eur: float  # I give (XE amount) — сверка EUR в банке
    payment_method: str
    amount_usd: float = 0.0  # I give USD (hz-calc без XE) — сверка USD в банке
    order_id: str = ""
