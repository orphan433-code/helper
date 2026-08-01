"""Разблокировка Activ Bank — PIN-клавиатура (4 тапа, warp)."""

from __future__ import annotations

import re
import time

from config_loader import bank_settings, capture_region_or_raise
from input_device import tap_sequence
from ocr import OcrHit, find_digit, find_text, run_ocr
from screenshot import take_screenshot


class PinUnlockError(RuntimeError):
    pass


def validate_pin(raw: str) -> str:
    pin = raw.strip()
    if not re.fullmatch(r"\d{4}", pin):
        raise PinUnlockError("PIN должен быть ровно 4 цифры, например: 1234")
    return pin


def pin_from_config(cfg: dict | None = None) -> str:
    raw = str(bank_settings(cfg).get("pin") or "").strip()
    if not raw:
        raise PinUnlockError("bank.pin не задан в config.yaml")
    return validate_pin(raw)


def _tap_settings() -> dict:
    bank = bank_settings()
    return {
        "pre_tap_sec": float(bank.get("pin_pre_tap_sec", 0.6)),
        "mirror_focus_sec": float(bank.get("mirror_focus_sec", 0.45)),
        "gap_sec": float(bank.get("pin_tap_gap_sec", 0.3)),
        "same_gap_sec": float(bank.get("pin_tap_same_gap_sec", 0.45)),
        "warp_sec": float(bank.get("pin_tap_warp_sec", 0.05)),
        "first_warp_sec": float(bank.get("pin_first_tap_warp_sec", 0.15)),
        "first_hold_sec": float(bank.get("pin_first_tap_hold_sec", 0.08)),
        "hold_sec": float(bank.get("pin_tap_hold_sec", 0.05)),
        "settle_sec": float(bank.get("pin_tap_settle_sec", 0.08)),
        "first_settle_sec": float(bank.get("pin_first_tap_settle_sec", 0.18)),
        "first_tap_twice": bool(bank.get("pin_first_tap_twice", True)),
        "first_retry_gap_sec": float(bank.get("pin_first_retry_gap_sec", 0.4)),
        "prime_tap": bool(bank.get("pin_prime_tap", True)),
        "prime_settle_sec": float(bank.get("pin_prime_settle_sec", 0.25)),
        "prime_y_offset": float(bank.get("pin_prime_y_offset", -130)),
    }


def _prime_point(
    points: list[tuple[float, float]],
    hits: list[OcrHit],
) -> tuple[float, float]:
    title = find_text(hits, "Activ Bank", partial=True)
    if title is not None:
        return title.x, title.y
    x, y = points[0]
    cfg = _tap_settings()
    return x, y + cfg["prime_y_offset"]


def _all_same_tap(points: list[tuple[float, float]]) -> bool:
    if len(points) < 2:
        return True
    x0, y0 = int(round(points[0][0])), int(round(points[0][1]))
    return all(int(round(x)) == x0 and int(round(y)) == y0 for x, y in points)


def _keypad_ocr_hits(
    image,
    capture: tuple[int, int, int, int],
) -> list[OcrHit]:
    """OCR нижней части экрана — PIN-клавиатура без цифр из статус-бара."""
    _left, _top, rw, rh = capture
    pad_top = int(rh * 0.32)
    crop = image.crop((0, pad_top, rw, rh))
    sub = (0, pad_top, rw, rh - pad_top)
    pad_hits = run_ocr(crop, region=sub)
    full_hits = run_ocr(image, region=capture)

    text_hits = [
        h
        for h in full_hits
        if not (len(h.text.strip()) == 1 and h.text.strip().isdigit())
    ]
    digits: dict[str, OcrHit] = {}
    for hit in pad_hits:
        key = hit.text.strip()
        if key in ("O", "o"):
            key = "0"
        if len(key) == 1 and key.isdigit():
            digits[key] = hit
    if not digits:
        for hit in full_hits:
            key = hit.text.strip()
            if key in ("O", "o"):
                key = "0"
            if len(key) == 1 and key.isdigit():
                digits[key] = hit
    from ocr import enrich_keypad_digits

    return enrich_keypad_digits(text_hits + list(digits.values()))


def wait_for_keypad(
    region: tuple[int, int, int, int],
    *,
    timeout_sec: float = 30.0,
    check_digits: tuple[str, ...] = ("1", "5"),
) -> list[OcrHit]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        image = take_screenshot(region=region)
        hits = run_ocr(image, region=region)
        if all(find_digit(hits, d) for d in check_digits):
            return hits
    raise PinUnlockError("PIN-клавиатура не найдена за отведённое время")


def pin_to_taps(
    pin: str,
    hits: list[OcrHit],
    *,
    verbose: bool = True,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    from ocr import enrich_keypad_digits

    hits = enrich_keypad_digits(hits)
    for i, digit in enumerate(pin, start=1):
        hit = find_digit(hits, digit)
        if hit is None:
            known = sorted(
                {h.text for h in hits if len(h.text) == 1 and h.text.isdigit()}
            )
            raise PinUnlockError(
                f"Цифра {digit!r} (позиция {i}/4) не найдена. "
                f"На экране: {', '.join(known) or '—'}"
            )
        if verbose:
            tag = " calc" if hit.inferred else ""
            print(f"  [{i}/4] {digit} → ({hit.x:.0f}, {hit.y:.0f}){tag}")
        points.append((hit.x, hit.y))
    return points


def unlock_pin(
    pin: str,
    *,
    region: tuple[int, int, int, int] | None = None,
    hits: list[OcrHit] | None = None,
    verbose: bool = True,
) -> None:
    pin = validate_pin(pin)
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    # Свежий скрин: клавиатура снизу (без цифр из статус-бара)
    image = take_screenshot(region=capture)
    hits = _keypad_ocr_hits(image, capture)

    taps = _tap_settings()
    if verbose:
        print("[INFO] Координаты тапов:")
    points = pin_to_taps(pin, hits, verbose=verbose)
    prime = _prime_point(points, hits) if taps["prime_tap"] else None

    repeat_first = False
    if verbose:
        print(
            f"\n[INFO] PIN: фокус → primer → 4 тапа "
            f"(повтор 1-го: {repeat_first})…"
        )

    tap_sequence(
        points,
        restore_cursor=True,
        refocus_mirror=True,
        mirror_focus_sec=taps["mirror_focus_sec"],
        pre_tap_sec=taps["pre_tap_sec"],
        prime_point=prime,
        prime_settle_sec=taps["prime_settle_sec"],
        first_tap_twice=repeat_first,
        first_retry_gap_sec=taps["first_retry_gap_sec"],
        gap_sec=taps["gap_sec"],
        same_gap_sec=taps["same_gap_sec"],
        warp_sec=taps["warp_sec"],
        first_warp_sec=taps["first_warp_sec"],
        first_hold_sec=taps["first_hold_sec"],
        hold_sec=taps["hold_sec"],
        settle_sec=taps["settle_sec"],
        first_settle_sec=taps["first_settle_sec"],
        verbose=verbose,
        wake_device=not bool(bank_settings().get("pin_skip_wake", True)),
    )

    if verbose:
        print("[OK] PIN отправлен")
