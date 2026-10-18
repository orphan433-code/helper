"""Каким банком платим в текущем цикле. Activ не трогает Alif и наоборот."""

from __future__ import annotations

from contextvars import ContextVar, Token

PAYOUT_ACTIV = "activ"
PAYOUT_ALIF = "alif"

_bank: ContextVar[str] = ContextVar("payout_bank", default=PAYOUT_ACTIV)


def normalize_payout_bank(raw: object) -> str:
    key = str(raw or "").strip().lower()
    if key == PAYOUT_ALIF:
        return PAYOUT_ALIF
    return PAYOUT_ACTIV


def set_payout_bank(raw: object) -> Token[str]:
    return _bank.set(normalize_payout_bank(raw))


def reset_payout_bank(token: Token[str]) -> None:
    _bank.reset(token)


def payout_bank() -> str:
    return _bank.get()


def is_alif() -> bool:
    return payout_bank() == PAYOUT_ALIF


class _BankScope:
    def __init__(self, raw: object) -> None:
        self._token = set_payout_bank(raw)

    def __enter__(self) -> str:
        return payout_bank()

    def __exit__(self, *exc: object) -> None:
        reset_payout_bank(self._token)


def use_payout_bank(raw: object) -> _BankScope:
    """На время вызова. Превью чеков идёт в другом потоке, без контекста цикла."""
    return _BankScope(raw)
