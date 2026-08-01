"""Тапы и ввод через adb (Android)."""

from __future__ import annotations

import time

from adb_device import keyevent, swipe_raw, tap_raw, wake_screen
from config_loader import bank_settings


def _jitter(x: float, y: float) -> tuple[int, int]:
    from bank_human import tap_xy

    return tap_xy(x, y)


def focus_device(*, settle_sec: float = 0.35, wake: bool = True) -> None:
    if wake:
        wake_screen()
    if settle_sec > 0:
        time.sleep(settle_sec)


def tap_at(
    x: float,
    y: float,
    *,
    restore_cursor: bool = True,  # noqa: ARG001 — совместимость API
    warp_sec: float = 0.05,
    hold_sec: float = 0.05,  # noqa: ARG001
    settle_sec: float = 0.08,
) -> None:
    ix, iy = _jitter(x, y)
    if warp_sec > 0:
        time.sleep(warp_sec)
    tap_raw(ix, iy)
    gap = max(settle_sec, 0.0)
    if gap > 0:
        time.sleep(gap)


def tap_point(
    x: float,
    y: float,
    *,
    refocus_mirror: bool = True,
    mirror_focus_sec: float = 0.4,
    pre_tap_sec: float = 0.35,
    verbose: bool = False,
    label: str = "",
) -> None:
    if refocus_mirror:
        focus_device(settle_sec=mirror_focus_sec)
    if pre_tap_sec > 0:
        time.sleep(pre_tap_sec)
    if verbose:
        suffix = f" — {label}" if label else ""
        ix, iy = _jitter(x, y)
        print(f"    → adb tap ({ix}, {iy}){suffix}")
    tap_at(x, y, restore_cursor=False, warp_sec=0.0, settle_sec=0.05)


def tap_sequence(
    points: list[tuple[float, float]],
    *,
    restore_cursor: bool = True,  # noqa: ARG001
    refocus_mirror: bool = True,
    mirror_focus_sec: float = 0.35,
    pre_tap_sec: float = 0.0,
    prime_point: tuple[float, float] | None = None,
    prime_settle_sec: float = 0.25,
    first_tap_twice: bool = False,
    first_retry_gap_sec: float = 0.4,
    gap_sec: float = 0.3,
    same_gap_sec: float = 0.45,
    warp_sec: float = 0.05,
    first_warp_sec: float | None = None,  # noqa: ARG001
    first_hold_sec: float | None = None,  # noqa: ARG001
    hold_sec: float = 0.05,  # noqa: ARG001
    settle_sec: float = 0.08,
    first_settle_sec: float | None = None,
    verbose: bool = False,
    wake_device: bool = True,
) -> None:
    if not points:
        return

    if refocus_mirror:
        focus_device(settle_sec=mirror_focus_sec, wake=wake_device)
    if pre_tap_sec > 0:
        if verbose:
            print(f"    … пауза {pre_tap_sec:g} с перед тапами")
        time.sleep(pre_tap_sec)

    first_settle = first_settle_sec if first_settle_sec is not None else settle_sec

    if prime_point is not None:
        px, py = prime_point
        if verbose:
            print(f"    ◦ primer ({px:.0f}, {py:.0f})")
        tap_at(px, py, restore_cursor=False, warp_sec=0.08, settle_sec=0.1)
        if prime_settle_sec > 0:
            time.sleep(prime_settle_sec)

    for i, (x, y) in enumerate(points):
        is_first = i == 0
        if verbose:
            print(f"    → tap {i + 1}/{len(points)} @ ({x:.0f}, {y:.0f})")
        tap_at(
            x,
            y,
            restore_cursor=False,
            warp_sec=warp_sec,
            settle_sec=first_settle if is_first else settle_sec,
        )
        if is_first and first_tap_twice:
            if first_retry_gap_sec > 0:
                time.sleep(first_retry_gap_sec)
            if verbose:
                print(f"    → повтор 1/{len(points)} @ ({x:.0f}, {y:.0f})")
            tap_at(x, y, restore_cursor=False, warp_sec=warp_sec, settle_sec=settle_sec)

        if i + 1 >= len(points):
            continue
        nx, ny = points[i + 1]
        same = int(round(x)) == int(round(nx)) and int(round(y)) == int(round(ny))
        gap = same_gap_sec if same else gap_sec
        if gap > 0:
            time.sleep(gap)


def ime_action(*, settle_sec: float = 0.2, verbose: bool = False, label: str = "") -> None:
    """
    Кнопка действия IME (Gboard): «Далее» / галочка Done.

    KEYCODE_ENTER на soft-keyboard жмёт именно action-кнопку, не сабмит формы.
    """
    if verbose:
        tag = f" — {label}" if label else ""
        print(f"    ⌨ IME action{tag}")
    keyevent("KEYCODE_ENTER")
    if settle_sec > 0:
        time.sleep(settle_sec)


def ime_next(*, settle_sec: float = 0.25, verbose: bool = False) -> None:
    """«Далее» на клаве → фокус на следующее поле."""
    ime_action(settle_sec=settle_sec, verbose=verbose, label="Далее")


def ime_done(*, settle_sec: float = 0.3, verbose: bool = False) -> None:
    """Галочка на сумме = тот же Enter (KEYCODE_ENTER), клава закрывается."""
    ime_action(settle_sec=settle_sec, verbose=verbose, label="Готово/Enter")


def dismiss_keyboard(*, interval: float = 0.08) -> None:
    """
    Скрыть клавиатуру.

    Предпочтительно ime_done() после последнего поля.
    Fallback: тап по верхней зоне (не Back — уводит с формы).
    """
    from adb_device import get_display_size, tap_raw

    w, h = get_display_size()
    tap_raw(max(w // 2, 1), max(int(h * 0.12), 1))
    if interval > 0:
        time.sleep(interval)


def tap_keyboard_globe(
    *,
    region: tuple[int, int, int, int] | None = None,  # noqa: ARG001
    x: float | None = None,
    y: float | None = None,
    taps: int = 0,
    settle_sec: float = 0.3,  # noqa: ARG001
    verbose: bool = False,  # noqa: ARG001
) -> None:
    """На Android раскладка обычно не нужна — noop."""
    if taps <= 0 or x is None or y is None:
        return


def paste_text(text: str, *, clear: bool = False, digits: bool = False) -> None:
    """
    Ввод в сфокусированное поле.

    digits=True — keyevent по цифрам (numeric IME / сумма списания).
    иначе — adb input text (карта, латиница ФИО).
    """
    from adb_device import type_digits_raw, type_text_raw

    if clear:
        keyevent("KEYCODE_MOVE_END")
        for _ in range(min(max(len(text) + 8, 24), 48)):
            keyevent("KEYCODE_DEL")
        time.sleep(0.05)

    if digits:
        type_digits_raw(text)
        return
    type_text_raw(text)

def scroll_carousel_horizontal(
    x: float,
    y: float,
    *,
    pixels: int = -8,  # noqa: ARG001
    lines: int = 5,  # noqa: ARG001
    pulses: int = 3,
    pulse_gap_sec: float = 0.15,
    method: str = "pixel",
    swipe_length: float = 110,
    refocus_mirror: bool = True,
    mirror_focus_sec: float = 0.35,
    pre_scroll_sec: float = 0.15,
    restore_cursor: bool = True,  # noqa: ARG001
    verbose: bool = False,
) -> str:
    if refocus_mirror:
        focus_device(settle_sec=mirror_focus_sec)
    if pre_scroll_sec > 0:
        time.sleep(pre_scroll_sec)

    ix, iy = int(round(x)), int(round(y))
    half = swipe_length / 2
    if method == "swipe" or swipe_length > 20:
        x_start = int(ix + half)
        x_end = int(ix - half)
    else:
        x_start = int(ix + 40)
        x_end = int(ix - 40)

    used = "swipe"
    for pulse in range(max(pulses, 1)):
        swipe_raw(x_start, iy, x_end, iy, duration_ms=320)
        if verbose:
            print(f"    ↔ adb swipe ({x_start}, {iy}) → ({x_end}, {iy}) {pulse + 1}/{pulses}")
        if pulse_gap_sec > 0 and pulse + 1 < pulses:
            time.sleep(pulse_gap_sec)
    return used


def ensure_us_keyboard(*, settle_sec: float = 0.15) -> None:
    if settle_sec > 0:
        time.sleep(0)


def quick_scroll_form_down(
    *,
    duration_ms: int = 140,
    top_ratio: float = 0.55,
    bottom_ratio: float = 0.30,
    settle_sec: float = 0.2,
    pulses: int = 1,
    pulse_gap_sec: float = 0.1,
    verbose: bool = False,
) -> None:
    """
    Быстрый вертикальный swipe внутри формы (ScrollView) — докручивает до
    конца формы (кнопка «Продолжить» и т.п.), даже если Gboard открыт и
    подрезал viewport снизу, а тап-скрытие клавы не помогает.

    Диапазон top_ratio/bottom_ratio держим выше типичной высоты клавиатуры,
    чтобы не задеть саму Gboard свайпом. pulses>1 — несколько проходов
    подряд, чтобы докрутить до упора (ScrollView сам стопорится на конце).
    """
    from adb_device import get_display_size

    w, h = get_display_size()
    x = w // 2
    y_start = int(h * top_ratio)
    y_end = int(h * bottom_ratio)
    for i in range(max(pulses, 1)):
        if verbose:
            print(f"    ↕ быстрый scroll формы ({x}, {y_start}) → ({x}, {y_end}) {i + 1}/{pulses}")
        swipe_raw(x, y_start, x, y_end, duration_ms=duration_ms)
        if i + 1 < pulses and pulse_gap_sec > 0:
            time.sleep(pulse_gap_sec)
    if settle_sec > 0:
        time.sleep(settle_sec)
