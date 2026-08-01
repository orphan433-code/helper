"""Быстрый вход в банк после Accept: один фокус + один OCR."""

from __future__ import annotations

import time

from bank_screen import is_pin_screen, scan_screen, wait_for_manual_pin
from config_loader import bank_settings, capture_region_or_raise
from gui_hooks import is_gui_mode
from input_device import focus_iphone_mirror
from ocr import OcrHit, find_any_text, find_text


def handoff_focus_sec(cfg: dict | None = None) -> float:
    bank = bank_settings(cfg)
    if bank.get("bank_handoff_focus_sec") is not None:
        return float(bank["bank_handoff_focus_sec"])
    return float(bank.get("bank_pre_focus_sec", 0.35))


def _bank_ready_markers(cfg: dict | None = None) -> list[str]:
    bank = bank_settings(cfg)
    payments = str(bank.get("label_payments", "Платежи"))
    transfers = str(bank.get("label_transfers", "Переводы"))
    markers: list[str] = [payments, transfers, "Главная", "Activ", "ActivBank"]
    for raw in bank.get("pin_screen_markers") or []:
        text = str(raw).strip()
        if text and text not in markers:
            markers.append(text)
    return markers


def _screen_looks_like_bank(hits: list[OcrHit], cfg: dict | None = None) -> bool:
    markers = _bank_ready_markers(cfg)
    if find_any_text(hits, markers, partial=True) is not None:
        return True
    if is_pin_screen(hits, cfg=cfg):
        return True
    return find_text(hits, "Переводы", partial=True) is not None


def _focus_device_for_handoff(cfg: dict | None = None) -> None:
    """Wake/фокус Android-устройства перед OCR банка."""
    bank = bank_settings(cfg)
    settle = handoff_focus_sec(cfg)
    if is_gui_mode():
        settle = float(bank.get("bank_handoff_gui_focus_sec", max(settle, 0.45)))

    focus_iphone_mirror(settle_sec=settle)
    if is_gui_mode() and bool(bank.get("bank_handoff_gui_focus_retry", True)):
        time.sleep(0.08)
        focus_iphone_mirror(settle_sec=settle)


def _scan_bank_when_ready(
    capture: tuple[int, int, int, int],
    cfg: dict | None = None,
) -> tuple[list[OcrHit], float]:
    """
    После Accept браузер PlatCore на переднем плане — банк на телефоне мог уйти в фон.
    Ждём узнаваемый экран Activ Bank; периодически будим устройство.
    """
    bank = bank_settings(cfg)
    timeout = float(bank.get("bank_handoff_ready_timeout_sec", 6.0))
    poll = float(bank.get("bank_handoff_ready_poll_sec", 0.22))
    ocr_settle = float(bank.get("bank_handoff_ocr_settle_sec", 0.15))
    refocus_every = max(1, int(bank.get("bank_handoff_ready_refocus_every", 3)))

    _focus_device_for_handoff(cfg)
    if ocr_settle > 0:
        time.sleep(ocr_settle)

    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        hits = scan_screen(capture)
        if _screen_looks_like_bank(hits, cfg):
            return hits, time.monotonic()

        if attempt % refocus_every == 0:
            _focus_device_for_handoff(cfg)
            if ocr_settle > 0:
                time.sleep(ocr_settle)
        else:
            time.sleep(poll)

    hits = scan_screen(capture)
    return hits, time.monotonic()


def run_handoff_entry(
    *,
    region: tuple[int, int, int, int] | None = None,
    cfg: dict | None = None,
    started_at: float | None = None,
) -> tuple[list[OcrHit], bool]:
    """
    Wake Android → OCR, пока не виден экран банка.

    Returns:
        (hits, is_pin_screen)
    """
    capture = region if region is not None else capture_region_or_raise()
    hits, ready_at = _scan_bank_when_ready(capture, cfg)
    pin = is_pin_screen(hits, cfg=cfg)

    if started_at is not None:
        from logkit import debug, info

        total_ms = (time.monotonic() - started_at) * 1000
        ready_ms = (ready_at - started_at) * 1000
        mode = "GUI" if is_gui_mode() else "CLI"
        info(
            f"Handoff [{mode}]: банк на экране за {ready_ms:.0f} ms "
            f"(всего {total_ms:.0f} ms, {'PIN' if pin else 'nav'})"
        )
        if not _screen_looks_like_bank(hits, cfg):
            debug("Handoff: таймаут готовности — используем последний OCR-скан")

    return hits, pin


def wait_pin_if_needed(
    region: tuple[int, int, int, int],
    *,
    is_pin: bool,
    verbose: bool = False,
) -> None:
    if not is_pin:
        return
    wait_for_manual_pin(region, verbose=verbose)
