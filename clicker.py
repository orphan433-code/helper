"""Умный кликер: OCR + клик, динамическое ожидание (Android adb)."""

from __future__ import annotations

import logging
import time

from config_loader import bank_settings, capture_region, ocr_settings
from input_device import tap_at, tap_point
from ocr import find_text, run_ocr
from screenshot import take_screenshot

log = logging.getLogger(__name__)


class ClickTimeoutError(TimeoutError):
    pass


class ClickRetryError(RuntimeError):
    pass


def _click_cfg() -> tuple[float, int, tuple[int, int, int, int] | None]:
    cfg = ocr_settings()
    timeout = float(cfg.get("click_timeout_sec", 30.0))
    retries = int(cfg.get("click_retry_count", 3))
    region = capture_region()
    return timeout, retries, region


def wait_for_text(
    target: str,
    *,
    region: tuple[int, int, int, int] | None = None,
    timeout_sec: float | None = None,
    partial: bool = True,
) -> tuple[float, float]:
    default_timeout, _, default_region = _click_cfg()
    deadline = time.monotonic() + (timeout_sec or default_timeout)
    capture = region if region is not None else default_region

    while time.monotonic() < deadline:
        image = take_screenshot(region=capture)
        hits = run_ocr(image, region=capture)
        hit = find_text(hits, target, partial=partial)
        if hit is not None:
            log.info("Найден %r → (%.0f, %.0f)", hit.text, hit.x, hit.y)
            return hit.x, hit.y

    raise ClickTimeoutError(
        f"Текст {target!r} не найден за {timeout_sec or default_timeout:.0f} с"
    )


def wait_and_click(
    target: str,
    *,
    region: tuple[int, int, int, int] | None = None,
    timeout_sec: float | None = None,
    retries: int | None = None,
    partial: bool = True,
) -> None:
    _, default_retries, _ = _click_cfg()
    last_error: Exception | None = None
    attempts = retries if retries is not None else default_retries

    for attempt in range(1, attempts + 1):
        try:
            x, y = wait_for_text(
                target,
                region=region,
                timeout_sec=timeout_sec,
                partial=partial,
            )
            tap_at(x, y)
            log.info("Тап по %r (%d/%d)", target, attempt, attempts)
            return
        except (ClickTimeoutError, OSError) as exc:
            last_error = exc
            log.warning("Попытка %d/%d: %s", attempt, attempts, exc)

    raise ClickRetryError(
        f"Не удалось кликнуть по {target!r} за {attempts} попыток"
    ) from last_error


def tap_after_ocr(
    x: float,
    y: float,
    *,
    verbose: bool = False,
    label: str = "",
    refocus: bool | None = None,
    pre_tap_sec: float | None = None,
) -> None:
    """Тап по координатам сразу после OCR — без лишнего wake/pre_tap."""
    cfg = bank_settings()
    immediate = bool(cfg.get("tap_after_ocr_immediate", True))
    mirror = float(cfg.get("mirror_focus_sec", 0.4))

    if immediate:
        do_refocus = False if refocus is None else refocus
        pre = (
            float(cfg.get("tap_after_ocr_pre_sec", 0.0))
            if pre_tap_sec is None
            else pre_tap_sec
        )
    else:
        do_refocus = True if refocus is None else refocus
        pre = (
            float(cfg.get("form_pre_tap_sec", 0.28))
            if pre_tap_sec is None
            else pre_tap_sec
        )

    from bank_human import click_pause

    click_pause(cfg)

    tap_point(
        x,
        y,
        refocus_mirror=do_refocus,
        mirror_focus_sec=mirror,
        pre_tap_sec=pre,
        verbose=verbose,
        label=label,
    )


def try_allow_paste_permission(*, verbose: bool = True) -> bool:
    """iOS-диалог вставки — на Android не нужен."""
    _ = verbose
    return False


def paste_text(
    text: str,
    *,
    clear: bool = False,
    verbose: bool = True,
    digits: bool = False,
) -> None:
    """Ввод в поле: input text или keyevent-цифры."""
    _ = verbose
    from input_adb import paste_text as adb_paste

    adb_paste(text, clear=clear, digits=digits)


def type_keys(text: str, *, interval: float = 0.04, clear: bool = False) -> None:
    """На Android — adb type."""
    _ = interval
    if not text:
        return
    paste_text(text, clear=clear)


def input_field_text(
    text: str,
    *,
    method: str = "hardware",
    interval: float = 0.04,
    clear: bool = False,
) -> bool | None:
    _ = interval
    method_l = (method or "hardware").strip().lower()
    if method_l in ("softkey", "ui", "tapkey", "amount"):
        from softkey import type_amount_smart

        return type_amount_smart(text, verbose=True)
    use_digits = method_l in ("digits", "numeric")
    paste_text(text, clear=clear, digits=use_digits)
    return None


def type_text(text: str) -> None:
    input_field_text(text, method="hardware", clear=True)
