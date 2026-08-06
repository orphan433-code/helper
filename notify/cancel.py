"""Фоновый мониторинг отмен списания в Android-шторке.

Якорь: «Otmena spisaniya» / «Отмена списания».
Включается на время приёма сделок; после конца — ещё grace_sec, потом стоп.

Отмену сопоставляем с недавними выплатами: карта (****) и сумма
(как в банке TJS или списанная с комиссией ~1.8%).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any

from notify.sms import dump_notifications, parse_notifications

CancelHandler = Callable[[dict[str, Any]], None]

# Activ Bank: списание ≈ сумма перевода × (1 + fee). 4664.43 → 4748.39 = +1.8%.
_DEFAULT_FEE_RATE = 0.018
_AMOUNT_TOL_TJS = 1.5  # допуск округления при матче

_OTMENA_RE = re.compile(
    r"otmena\s+spisaniya|отмена\s+списания",
    re.IGNORECASE,
)
_CARD_RE = re.compile(r"(?:\*{2,}|\bKarta\b|\bКарта\b)\s*[*]*\s*(\d{4})", re.I)
_SUMMA_RE = re.compile(
    r"(?:Summa|Сумма)\s*([0-9]+(?:[.,][0-9]+)?)\s*(TJS|USD|EUR|GEL)?",
    re.I,
)
_BALANS_RE = re.compile(
    r"(?:Balans|Баланс)\s*([0-9]+(?:[.,][0-9]+)?)\s*(TJS|USD|EUR|GEL)?",
    re.I,
)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_stop_after_mono: float | None = None
_seen_keys: set[str] = set()
_handler: CancelHandler | None = None
_poll_sec = 1.7
_verbose = True
_fee_rate = _DEFAULT_FEE_RATE
# Недавние успешные переводы этой сессии (для сопоставления с отменой).
_paid_deals: list[dict[str, Any]] = []


def set_cancel_handler(handler: CancelHandler | None) -> None:
    global _handler
    with _lock:
        _handler = handler


def clear_paid_deals() -> None:
    with _lock:
        _paid_deals.clear()


def register_paid_deal(
    *,
    index: int,
    holder: str,
    card_digits: str,
    amount_tjs: float,
    order_id: str = "",
) -> None:
    """Запомнить выплату — чтобы отмена из шторки нашлась по карте/сумме."""
    digits = "".join(ch for ch in str(card_digits) if ch.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else ""
    row = {
        "index": int(index),
        "holder": (holder or "").strip(),
        "card_last4": last4,
        "card": f"*{last4}" if last4 else "",
        "amount_tjs": float(amount_tjs),
        "order_id": (order_id or "").strip(),
        "paid_at": time.time(),
        "matched": False,
    }
    with _lock:
        _paid_deals.append(row)
        if len(_paid_deals) > 40:
            del _paid_deals[:-40]
    if _verbose:
        print(
            f"[INFO] Отмены: учли выплату #{row['index']} "
            f"{row['card'] or '????'} {row['amount_tjs']:g} TJS "
            f"«{row['holder'] or '—'}»"
        )


def _parse_amount_num(amount_str: str) -> float | None:
    raw = (amount_str or "").strip().split()[0] if amount_str else ""
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _amount_candidates(deal_tjs: float, fee_rate: float) -> list[float]:
    """Возможные суммы в SMS: сам перевод или списание с комиссией."""
    fee = max(0.0, float(fee_rate))
    out = [deal_tjs, deal_tjs * (1.0 + fee)]
    if fee < 1:
        out.append(deal_tjs / (1.0 + fee))
    return out


def match_paid_deal(
    parsed: dict[str, Any],
    *,
    fee_rate: float | None = None,
    amount_tol: float = _AMOUNT_TOL_TJS,
) -> dict[str, Any] | None:
    """Найти ближайшую несопоставленную выплату под отмену.

    Важно: «Karta ***» в SMS отмены — обычно карта СПИСАНИЯ (наш Activ),
    а не карта получателя из сделки. Поэтому карта — только мягкий бонус,
    главный якорь — сумма (перевод или списание с комиссией ~1.8%).
    """
    fee = _DEFAULT_FEE_RATE if fee_rate is None else float(fee_rate)
    cancel_last4 = "".join(
        ch for ch in str(parsed.get("card") or "") if ch.isdigit()
    )[-4:]
    cancel_amt = _parse_amount_num(str(parsed.get("amount") or ""))
    if cancel_amt is None:
        return None

    with _lock:
        pool = [d for d in _paid_deals if not d.get("matched")]

    best: dict[str, Any] | None = None
    best_score = -1.0

    for deal in pool:
        if deal["amount_tjs"] <= 0:
            continue
        diffs = [
            abs(cancel_amt - cand)
            for cand in _amount_candidates(deal["amount_tjs"], fee)
        ]
        min_diff = min(diffs)
        if min_diff > amount_tol:
            continue

        # Чем ближе сумма — тем выше балл
        score = 100.0 - min_diff * 10.0
        if cancel_last4 and deal["card_last4"] and cancel_last4 == deal["card_last4"]:
            score += 15.0  # редко, но если совпало — плюс
        age = max(0.0, time.time() - float(deal.get("paid_at") or 0))
        score += max(0.0, 10.0 - age / 60.0)

        if score > best_score:
            best_score = score
            best = deal

    if best is None:
        return None

    with _lock:
        best["matched"] = True

    label_parts = []
    if best.get("index"):
        label_parts.append(f"#{best['index']}")
    if best.get("holder"):
        label_parts.append(best["holder"])
    if best.get("card"):
        label_parts.append(f"карта {best['card']}")
    if best.get("amount_tjs"):
        label_parts.append(f"{best['amount_tjs']:g} TJS")
    return {
        "match_index": best.get("index"),
        "match_holder": best.get("holder") or "",
        "match_card": best.get("card") or "",
        "match_amount_tjs": best.get("amount_tjs"),
        "match_order_id": best.get("order_id") or "",
        "match_label": " · ".join(label_parts) if label_parts else "",
    }


def _emit(payload: dict[str, Any]) -> None:
    with _lock:
        h = _handler
    if h is not None:
        try:
            h(payload)
        except Exception:
            pass


def parse_cancel_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    hay = f"{rec.get('title', '')}\n{rec.get('text', '')}"
    if not _OTMENA_RE.search(hay):
        return None

    card = ""
    m_card = _CARD_RE.search(hay)
    if m_card:
        card = f"*{m_card.group(1)}"

    amount = ""
    m_sum = _SUMMA_RE.search(hay)
    if m_sum:
        amount = (
            f"{m_sum.group(1).replace(',', '.')} "
            f"{(m_sum.group(2) or 'TJS').upper()}"
        )

    balance = ""
    m_bal = _BALANS_RE.search(hay)
    if m_bal:
        balance = (
            f"{m_bal.group(1).replace(',', '.')} "
            f"{(m_bal.group(2) or 'TJS').upper()}"
        )

    return {
        "key": rec["key"],
        "pkg": rec.get("pkg") or "",
        "card": card,
        "amount": amount,
        "balance": balance,
        "raw": hay.strip()[:400],
        "when_ms": rec.get("when_ms"),
        "ts": time.strftime("%H:%M:%S"),
    }


def _loop() -> None:
    global _stop_after_mono
    if _verbose:
        print("[INFO] Отмены: мониторинг шторки включён (на время приёма)")

    try:
        for rec in parse_notifications(dump_notifications()):
            _seen_keys.add(rec["key"])
    except Exception as exc:
        if _verbose:
            print(f"[WARN] Отмены: стартовый dump не удался: {exc}")

    while not _stop.is_set():
        with _lock:
            stop_after = _stop_after_mono
            fee = _fee_rate
        if stop_after is not None and time.monotonic() >= stop_after:
            break
        try:
            records = parse_notifications(dump_notifications())
        except Exception as exc:
            if _verbose:
                print(f"[WARN] Отмены: dump failed: {exc}")
            _stop.wait(_poll_sec)
            continue

        for rec in records:
            key = rec["key"]
            if key in _seen_keys:
                continue
            _seen_keys.add(key)
            parsed = parse_cancel_record(rec)
            if parsed is None:
                continue
            match = match_paid_deal(parsed, fee_rate=fee)
            if match:
                parsed.update(match)
            if _verbose:
                bits = [parsed["ts"], "ОТМЕНА СПИСАНИЯ"]
                if parsed.get("card"):
                    bits.append(parsed["card"])
                if parsed.get("amount"):
                    bits.append(parsed["amount"])
                if parsed.get("match_label"):
                    bits.append("≈ " + parsed["match_label"])
                else:
                    bits.append("(сделка не сопоставлена)")
                print("[ALERT] " + " · ".join(bits))
            _emit(parsed)

        _stop.wait(_poll_sec)

    if _verbose:
        print("[INFO] Отмены: мониторинг шторки выключен")
    with _lock:
        global _thread
        _thread = None
        _stop_after_mono = None


def start_cancel_watch(
    *,
    poll_sec: float = 1.7,
    verbose: bool = True,
    fee_rate: float = _DEFAULT_FEE_RATE,
) -> None:
    """Запустить фон (идемпотентно). Пока идёт приём сделок."""
    global _thread, _poll_sec, _verbose, _stop_after_mono, _fee_rate
    with _lock:
        _poll_sec = max(0.8, float(poll_sec))
        _verbose = bool(verbose)
        _fee_rate = max(0.0, float(fee_rate))
        _stop_after_mono = None
        if _thread is not None and _thread.is_alive():
            _stop.clear()
            return
        _stop.clear()
        _seen_keys.clear()
        _paid_deals.clear()
        _thread = threading.Thread(
            target=_loop, name="tzk-cancel-watch", daemon=True
        )
        _thread.start()


def stop_cancel_watch(*, grace_sec: float = 45.0) -> None:
    """После конца приёма: ещё grace_sec слушать, потом выключить."""
    global _stop_after_mono
    with _lock:
        if _thread is None or not _thread.is_alive():
            return
        grace = max(0.0, float(grace_sec))
        if grace <= 0:
            _stop.set()
            _stop_after_mono = None
            return
        _stop_after_mono = time.monotonic() + grace
        if _verbose:
            print(
                f"[INFO] Отмены: ещё {grace:g} с после конца приёма, потом стоп"
            )


def stop_cancel_watch_now() -> None:
    """Немедленная остановка (Стоп / выключение сервера)."""
    global _stop_after_mono
    with _lock:
        _stop_after_mono = None
    _stop.set()
