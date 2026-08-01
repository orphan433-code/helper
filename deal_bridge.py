"""PlatCore TzkDeal → данные формы Activ Bank."""

from __future__ import annotations

import json
from pathlib import Path

from bank_form import TransferFormData
from config_loader import ROOT
from models import TzkDeal
from validators import PanicError, sanitize_holder_name_for_bank

PENDING_DEAL_PATH = ROOT / "pending_deal.json"


def deal_to_transfer_form(deal: TzkDeal) -> TransferFormData:
    account = (deal.account_digits or "").strip()
    holder = (deal.holder_name or "").strip()
    if not account:
        raise PanicError("Сделка без счёта — форму банка не заполнить")
    if not holder:
        raise PanicError("Сделка без имени получателя — форму банка не заполнить")
    if deal.amount_tjs <= 0:
        raise PanicError(f"Сумма TJS некорректна: {deal.amount_tjs}")

    bank_holder = sanitize_holder_name_for_bank(holder)
    if bank_holder != holder:
        print(f"[INFO] ФИО для банка: {holder!r} → {bank_holder!r}")

    return TransferFormData(
        account=account,
        holder_name=bank_holder,
        amount_tjs=deal.amount_tjs,
        amount_eur=deal.amount_eur if deal.amount_eur > 0 else None,
        amount_usd=deal.amount_usd if deal.amount_usd > 0 else None,
    )


def save_pending_deal(
    deal: TzkDeal,
    *,
    order_id: str = "",
    amount_eur_source: str = "",
) -> Path:
    """Сохранить принятую сделку — bank_flow читает отсюда."""
    payload = {
        "order_id": order_id or deal.order_id,
        "task_id": deal.task_id,
        "account": deal.account_digits,
        "account_raw": deal.account_raw,
        "holder_name": deal.holder_name,
        "amount_tjs": deal.amount_tjs,
        "amount_eur": deal.amount_eur,
        "amount_usd": deal.amount_usd,
        "amount_eur_source": amount_eur_source,
        "amount_check": deal.amount_check,
        "amount_check_currency": deal.amount_check_currency,
    }
    PENDING_DEAL_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return PENDING_DEAL_PATH


def load_pending_deal() -> TransferFormData | None:
    if not PENDING_DEAL_PATH.exists():
        return None
    try:
        payload = json.loads(PENDING_DEAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    account = str(payload.get("account") or "").strip()
    holder = str(payload.get("holder_name") or "").strip()
    amount = payload.get("amount_tjs")
    amount_eur = payload.get("amount_eur")
    amount_usd = payload.get("amount_usd")
    if not account or not holder or amount in (None, ""):
        return None
    eur = float(amount_eur) if amount_eur not in (None, "", 0) else None
    usd = float(amount_usd) if amount_usd not in (None, "", 0) else None
    return TransferFormData(
        account=account,
        holder_name=sanitize_holder_name_for_bank(holder),
        amount_tjs=float(amount),
        amount_eur=eur,
        amount_usd=usd,
    )
