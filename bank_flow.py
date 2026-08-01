#!/usr/bin/env python3
"""
Bank flow — Activ Bank (Android adb).

  python bank_flow.py

Этап 1: PIN-экран → ждём ручной ввод → дальше как обычно
Этап 2: Платежи → Переводы → scroll → Друг стра
Этап 3: По номеру карты → счёт, ФИО, TJS → EUR → 2× «Перевести»
Этап 3c: «Подтверждение перевода» → «Подтвердить и перевести»
Этап 4: SMS autofill «Источник: Life …»
Этап 5: «Детали перевода» → «На главную страницу»
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bank_form import BankFormError, TransferFormData, run_stage3_transfer_form, transfer_data_from_config
from bank_handoff import run_handoff_entry, wait_pin_if_needed
from deal_bridge import load_pending_deal
from bank_nav import BankNavError, run_stage2_payments
from bank_pin import PinUnlockError
from bank_screen import is_pin_screen, scan_screen, wait_for_manual_pin
from config_loader import bank_settings, capture_region_or_raise


class BankScreen(str, Enum):
    PIN = "pin"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageResult:
    screen: BankScreen
    action: str  # unlocked | skipped | timeout
    message: str = ""


def run_stage1_pin(
    *,
    region: tuple[int, int, int, int] | None = None,
    wait: bool = True,
    timeout_sec: float | None = None,
    focus_delay_sec: float | None = None,
    verbose: bool = True,
) -> StageResult:
    """Этап 1: если PIN-экран — ждём ручной ввод. Иначе skipped."""
    cfg = bank_settings()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    timeout = timeout_sec if timeout_sec is not None else float(cfg.get("stage_timeout_sec", 30))
    focus_delay = (
        focus_delay_sec if focus_delay_sec is not None else float(cfg.get("focus_delay_sec", 3))
    )
    manual_timeout = float(cfg.get("pin_manual_timeout_sec", 120))

    if focus_delay > 0:
        hits = scan_screen(capture)
        if not is_pin_screen(hits):
            if verbose:
                print("[INFO] PIN-экрана нет — пропускаем focus_delay")
            focus_delay = 0.0
        elif verbose:
            print(f"[INFO] Через {focus_delay:g} с — подготовка устройства\n")
        if focus_delay > 0:
            time.sleep(focus_delay)
    elif verbose:
        print("[INFO] Устройство готово — сразу к этапу 1\n")

    if wait:
        if verbose:
            print("[INFO] Этап 1: проверяем PIN-экран…")
        deadline = time.monotonic() + timeout
        poll = float(cfg.get("pin_poll_sec", 1.0))
        hits = None
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            hits = scan_screen(capture)
            if is_pin_screen(hits):
                if verbose:
                    print("[INFO] PIN-экран найден")
                found_settle = float(cfg.get("pin_screen_found_sec", 0.8))
                if found_settle > 0:
                    time.sleep(found_settle)
                break
            if verbose and attempt % max(1, int(2 / poll)) == 1:
                left = int(deadline - time.monotonic())
                sample = ", ".join(h.text for h in hits[:6]) or "—"
                print(f"    … ждём PIN (~{left}s), OCR: {sample}")
            time.sleep(poll)
        else:
            if verbose:
                print("[INFO] PIN-экрана нет — переходим к этапу 2")
            return StageResult(BankScreen.UNKNOWN, "skipped", "PIN-экран не на экране")
    else:
        hits = scan_screen(capture)
        if not is_pin_screen(hits):
            if verbose:
                print("[INFO] PIN-экран не найден — открой Activ Bank или добавь --wait-pin")
            return StageResult(BankScreen.UNKNOWN, "skipped", "PIN-экран не на экране")

    assert hits is not None
    if verbose:
        print("[INFO] PIN-экран — введите код вручную на телефоне")
    wait_for_manual_pin(
        capture,
        timeout_sec=timeout_sec if timeout_sec is not None else manual_timeout,
        verbose=verbose,
    )
    return StageResult(BankScreen.PIN, "unlocked")


def _resolve_transfer_data(
    *,
    account: str | None,
    holder: str | None,
    amount: float | None,
    amount_eur: float | None = None,
    from_deal: bool = False,
) -> TransferFormData | None:
    if account and holder and amount is not None:
        from validators import sanitize_holder_name_for_bank

        return TransferFormData(
            account=account.strip(),
            holder_name=sanitize_holder_name_for_bank(holder.strip()),
            amount_tjs=float(amount),
            amount_eur=float(amount_eur) if amount_eur is not None else None,
        )
    if from_deal:
        pending = load_pending_deal()
        if pending is not None:
            return pending
    return transfer_data_from_config()


def run_bank_flow(
    *,
    run_pin: bool = True,
    run_nav: bool = True,
    run_form: bool = True,
    transfer: TransferFormData | None = None,
    pin_wait: bool = False,
    timeout_sec: float | None = None,
    verbose: bool = True,
    handoff_started_at: float | None = None,
) -> None:
    region = capture_region_or_raise()
    if region is None:
        raise PinUnlockError("capture_region не задан")

    cfg = bank_settings()
    from_pipeline = handoff_started_at is not None
    handoff_fast = from_pipeline and bool(cfg.get("bank_handoff_fast", True))
    handoff_hits = None

    if handoff_fast:
        handoff_hits, is_pin = run_handoff_entry(
            region=region,
            started_at=handoff_started_at,
        )
        if run_pin and is_pin:
            if verbose:
                print("[INFO] PIN-экран — введите код на телефоне")
            wait_pin_if_needed(region, is_pin=True, verbose=verbose)
        elif run_pin and verbose:
            print("[INFO] PIN-экрана нет — сразу навигация")
    else:
        pre_focus = float(cfg.get("bank_pre_focus_sec", 1.5))
        if verbose:
            profile = cfg.get("timing_profile", "safe")
            print(f"[INFO] Bank flow ({profile}, Android adb): подготовка ({pre_focus:g} с)…")
        from input_device import focus_iphone_mirror

        focus_iphone_mirror(settle_sec=pre_focus)
        if handoff_started_at is not None:
            elapsed_ms = (time.monotonic() - handoff_started_at) * 1000
            from logkit import info

            info(f"Handoff: wake Android через {elapsed_ms:.0f} ms от Accept")

        if run_pin:
            result = run_stage1_pin(
                wait=pin_wait,
                timeout_sec=timeout_sec,
                verbose=verbose,
            )
            if verbose and result.action == "unlocked":
                print(f"[OK] Этап 1: {result.action}")
            elif verbose and result.action == "skipped":
                print(f"[INFO] Этап 1: пропущен — {result.message}")

    if run_nav:
        run_stage2_payments(
            region=region,
            verbose=verbose,
            initial_hits=handoff_hits,
            handoff_fast=handoff_fast,
        )

    if run_form:
        if transfer is None:
            if verbose:
                print("[INFO] Этап 3 пропущен — нет реквизитов (--account/--holder/--amount или config)")
            return
        run_stage3_transfer_form(transfer, region=region, verbose=verbose)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bank flow — Activ Bank (Android adb)")
    parser.add_argument(
        "--pin-only",
        action="store_true",
        help="только этап 1 (PIN)",
    )
    parser.add_argument(
        "--nav-only",
        action="store_true",
        help="только этап 2 (Платежи → другие страны)",
    )
    parser.add_argument(
        "--form-only",
        action="store_true",
        help="только этап 3 (форма: карта, ФИО, сумма)",
    )
    parser.add_argument(
        "--no-form",
        action="store_true",
        help="не заполнять форму после этапа 2",
    )
    parser.add_argument("--account", help="номер карты / счёта")
    parser.add_argument("--holder", help="фамилия имя получателя")
    parser.add_argument("--amount", type=float, help="сумма TJS, напр. 537.41")
    parser.add_argument("--amount-eur", type=float, help="сумма EUR для сверки, напр. 199.21")
    parser.add_argument(
        "--from-deal",
        action="store_true",
        help="реквизиты из pending_deal.json (последний Accept)",
    )
    parser.add_argument(
        "--wait-pin",
        action="store_true",
        help="ждать PIN-экран до timeout (иначе один скан и дальше)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="секунд ждать ручной ввод PIN (по умолчанию pin_manual_timeout_sec)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    run_pin = not args.nav_only and not args.form_only
    run_nav = not args.pin_only and not args.form_only
    run_form = not args.no_form and not args.pin_only and not args.nav_only
    pin_wait = args.wait_pin or args.pin_only

    transfer = _resolve_transfer_data(
        account=args.account,
        holder=args.holder,
        amount=args.amount,
        amount_eur=args.amount_eur,
        from_deal=args.from_deal,
    )
    if (args.form_only or run_form) and transfer is None and not args.no_form:
        if args.form_only:
            print(
                "\n[ERROR] Нет реквизитов: --from-deal, --account/--holder/--amount "
                "или pending_deal.json после Accept\n",
                file=sys.stderr,
            )
            return 1

    try:
        run_bank_flow(
            run_pin=run_pin,
            run_nav=run_nav,
            run_form=run_form,
            transfer=transfer,
            pin_wait=pin_wait,
            timeout_sec=args.timeout,
        )
    except (PinUnlockError, BankNavError, BankFormError) as exc:
        print(f"\n[ERROR] {exc}\n", file=sys.stderr)
        return 1

    print("\n[OK] bank_flow завершён")
    return 0


if __name__ == "__main__":
    sys.exit(main())
