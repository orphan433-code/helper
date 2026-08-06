"""Скан экрана Android + определение PIN-экрана."""

from __future__ import annotations

import time

from bank.pin import PinUnlockError
from core.config import bank_settings, capture_region_or_raise
from device.ocr import OcrHit, find_any_text, find_digit, find_text, run_ocr
from device.screenshot import take_screenshot


def scan_screen(
    region: tuple[int, int, int, int] | None = None,
) -> list[OcrHit]:
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")
    return run_ocr(take_screenshot(region=capture), region=capture)


def is_pin_screen(
    hits: list[OcrHit],
    *,
    cfg: dict | None = None,
) -> bool:
    settings = bank_settings(cfg)
    markers: list[str] = settings.get("pin_screen_markers") or [
        "Activ Bank",
        "ActivBank",
        "Введите PIN",
        "PIN-код",
        "PIN",
    ]
    check_digits: list[str] = settings.get("keypad_check_digits") or ["3", "6"]

    if find_any_text(hits, markers, partial=True) is None:
        # PIN-клавиатура без заголовка — достаточно цифр
        found = sum(1 for d in check_digits if find_digit(hits, d) is not None)
        if found < len(check_digits):
            return False
        # хотя бы 4 разные цифры на экране
        digits = {h.text for h in hits if len(h.text) == 1 and h.text.isdigit()}
        return len(digits) >= 4

    return all(find_digit(hits, d) for d in check_digits)


def find_label(
    hits: list[OcrHit],
    label: str,
    *,
    partial: bool = True,
) -> OcrHit | None:
    return find_text(hits, label, partial=partial)


def find_labels(
    hits: list[OcrHit],
    labels: list[str],
    *,
    partial: bool = True,
) -> OcrHit | None:
    return find_any_text(hits, labels, partial=partial)


def wait_for_manual_pin(
    region: tuple[int, int, int, int],
    *,
    timeout_sec: float | None = None,
    verbose: bool = True,
) -> None:
    """Ждём, пока пользователь сам введёт PIN (PIN-экран исчезнет)."""
    cfg = bank_settings()
    timeout = (
        timeout_sec
        if timeout_sec is not None
        else float(cfg.get("pin_manual_timeout_sec", 120))
    )
    poll = float(cfg.get("pin_poll_sec", 1.0))
    settle = float(cfg.get("post_pin_settle_sec", 0.8))

    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        if not is_pin_screen(scan_screen(region)):
            if verbose:
                print("[OK] PIN введён — продолжаем")
            if settle > 0:
                time.sleep(settle)
            return
        if verbose and attempt % max(1, int(3 / poll)) == 1:
            left = int(deadline - time.monotonic())
            print(f"    … введите PIN на телефоне (~{left}s)")
        time.sleep(poll)

    raise PinUnlockError(
        f"Таймаут {timeout:g} с — PIN-экран всё ещё открыт. "
        "Введите PIN вручную и перезапустите."
    )
