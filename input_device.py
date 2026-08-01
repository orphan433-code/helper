"""Единый вход ввода: Android через adb."""

from __future__ import annotations

from input_adb import (  # noqa: F401
    dismiss_keyboard,
    ensure_us_keyboard,
    focus_device,
    ime_done,
    ime_next,
    scroll_carousel_horizontal,
    tap_at,
    tap_keyboard_globe,
    tap_point,
    tap_sequence,
)

# Совместимость со старыми вызовами bank_* (раньше — focus iPhone Mirroring).
focus_iphone_mirror = focus_device


def prime_mirror_capture(
    region: tuple[int, int, int, int],
    *,
    settle_sec: float = 0.15,
) -> None:
    """Заглушка: adb screencap всегда даёт свежий кадр."""
    _ = region, settle_sec
