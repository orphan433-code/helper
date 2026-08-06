"""Bank flow — этап 2: Платежи → Переводы → scroll → Друг стра."""

from __future__ import annotations

import time

from bank.pin import PinUnlockError
from bank.screen import find_label, find_labels, scan_screen
from device.clicker import tap_after_ocr
from core.config import bank_settings, capture_region_or_raise
from device.input_device import scroll_carousel_horizontal
from device.ocr import OcrHit


class BankNavError(RuntimeError):
    pass


def _nav_cfg() -> dict:
    bank = bank_settings()
    return {
        "payments": str(bank.get("label_payments", "Платежи")),
        "transfers": str(bank.get("label_transfers", "Переводы")),
        "other_countries": bank.get("label_other_countries")
        or ["Друг стра", "Дру стра", "Друг", "дру", "стра"],
        "timeout": float(bank.get("nav_timeout_sec", 30)),
        "mirror_focus_sec": float(bank.get("mirror_focus_sec", 0.4)),
        "nav_pre_tap_sec": float(bank.get("nav_pre_tap_sec", 0.35)),
        "nav_step_gap_sec": float(bank.get("nav_step_gap_sec", 0.35)),
        "nav_post_tap_settle_sec": float(bank.get("nav_post_tap_settle_sec", 1.0)),
        "stage2_always_tap_payments": bool(bank.get("stage2_always_tap_payments", True)),
        "payments_tab_min_y_ratio": float(bank.get("payments_tab_min_y_ratio", 0.78)),
        "payments_fixed_tap_enabled": bool(bank.get("payments_fixed_tap_enabled", True)),
        "payments_fixed_x_ratio": float(bank.get("payments_fixed_x_ratio", 0.36)),
        "payments_fixed_y_ratio": float(bank.get("payments_fixed_y_ratio", 0.93)),
        "payments_ocr_timeout_sec": float(bank.get("payments_ocr_timeout_sec", 1.5)),
        "nav_mirror_wake_tap": bool(bank.get("nav_mirror_wake_tap", True)),
        "nav_first_tap_twice": bool(bank.get("nav_first_tap_twice", True)),
        "nav_first_tap_retry_gap_sec": float(bank.get("nav_first_tap_retry_gap_sec", 0.35)),
        "transfers_max_y_ratio": float(bank.get("transfers_max_y_ratio", 0.72)),
        "other_tap_icon_offset_y": float(bank.get("other_tap_icon_offset_y", 45)),
        "other_edge_tap_enabled": bool(bank.get("other_edge_tap_enabled", True)),
        "other_edge_x_ratio": float(bank.get("other_edge_x_ratio", 0.995)),
        "other_edge_right_inset": float(bank.get("other_edge_right_inset", 1)),
        "other_edge_y_offset": float(bank.get("other_edge_y_offset", 68)),
        "carousel_scroll_below_y": float(bank.get("carousel_scroll_below_y", 75)),
        "carousel_scroll_x_offset": float(bank.get("carousel_scroll_x_offset", 100)),
        "carousel_scroll_pixels": int(bank.get("carousel_scroll_pixels", -8)),
        "carousel_scroll_lines": int(bank.get("carousel_scroll_lines", 5)),
        "carousel_scroll_method": str(bank.get("carousel_scroll_method", "pixel")),
        "carousel_scroll_pulses": int(bank.get("carousel_scroll_pulses", 4)),
        "carousel_scroll_pulse_gap": float(bank.get("carousel_scroll_pulse_gap", 0.22)),
        "carousel_swipe_length": float(bank.get("carousel_swipe_length", 110)),
        "carousel_post_scroll_sec": float(bank.get("carousel_post_scroll_sec", 0.75)),
        "carousel_pre_scroll_sec": float(bank.get("carousel_pre_scroll_sec", 0.25)),
        "carousel_focus_sec": float(bank.get("carousel_focus_sec", 0.35)),
        "carousel_settle_sec": float(bank.get("carousel_settle_sec", 0.15)),
        "carousel_scroll_max_rounds": int(bank.get("carousel_scroll_max_rounds", 4)),
    }


_SCROLL_METHODS = ("pixel", "trackpad", "line", "swipe")


def _hit_y_ratio(hit: OcrHit, region: tuple[int, int, int, int]) -> float:
    _, top, _, height = region
    if height <= 0:
        return 0.0
    return (hit.y - top) / height


def hit_in_region(hit: OcrHit, region: tuple[int, int, int, int]) -> bool:
    """Координаты OCR внутри области экрана телефона (пиксели adb)."""
    left, top, width, height = region
    right = left + width
    bottom = top + height
    return left <= hit.x <= right and top <= hit.y <= bottom


def payments_tab_fallback_hit(
    region: tuple[int, int, int, int],
    nav: dict,
) -> OcrHit:
    """Стабильная координата нижнего таба, если OCR не видит подпись."""
    left, top, width, height = region
    return OcrHit(
        text=str(nav["payments"]),
        confidence=0.0,
        x=left + width * float(nav["payments_fixed_x_ratio"]),
        y=top + height * float(nav["payments_fixed_y_ratio"]),
        width=0.0,
        height=0.0,
        inferred=True,
    )


def find_payments_tab(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
    nav: dict,
) -> OcrHit | None:
    """
    «Платежи» для тапа — нижний таб-бар (высокий Y), не заголовок экрана.

    Заголовок «Платежи» вверху не переключает вкладку; OCR часто цепляет его первым.
    """
    needle = str(nav["payments"]).strip().lower()
    min_ratio = float(nav.get("payments_tab_min_y_ratio", 0.78))
    tab_best: OcrHit | None = None
    any_best: OcrHit | None = None

    for hit in hits:
        if needle not in hit.text.lower():
            continue
        if not hit_in_region(hit, region):
            continue
        if any_best is None or hit.confidence > any_best.confidence:
            any_best = hit
        if _hit_y_ratio(hit, region) >= min_ratio:
            if tab_best is None or hit.confidence > tab_best.confidence:
                tab_best = hit

    return tab_best or any_best


def is_payments_tab_active(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
    nav: dict,
) -> bool:
    """Уже на вкладке Платежи — в контенте виден якорь «Переводы»."""
    return find_transfers_content_anchor(hits, region, nav) is not None


def should_tap_payments_tab(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
    nav: dict,
) -> bool:
    """Учитывать принудительный тап, даже если OCR дал ложный активный экран."""
    return bool(nav["stage2_always_tap_payments"]) or not is_payments_tab_active(
        hits,
        region,
        nav,
    )


def tap_nav_target(
    x: float,
    y: float,
    *,
    verbose: bool = False,
    label: str = "",
    tap_twice: bool | None = None,
) -> None:
    """Тап по навигации после OCR (опционально wake + double-tap)."""
    bank = bank_settings()
    tag = f" — {label}" if label else ""
    if verbose:
        print(f"    → nav-тап ({x:.0f}, {y:.0f}){tag}")

    if not bool(bank.get("nav_mirror_wake_tap", True)):
        tap_after_ocr(x, y, verbose=verbose, label=label, refocus=True)
        return

    from device.input_device import focus_iphone_mirror, tap_sequence

    focus_iphone_mirror(settle_sec=float(bank.get("mirror_focus_sec", 0.45)))
    tap_sequence(
        [(x, y)],
        refocus_mirror=False,
        pre_tap_sec=float(bank.get("nav_pre_tap_sec", 0.25)),
        first_tap_twice=(
            bool(bank.get("nav_first_tap_twice", False))
            if tap_twice is None
            else tap_twice
        ),
        first_retry_gap_sec=float(bank.get("nav_first_tap_retry_gap_sec", 0.35)),
        gap_sec=0.2,
        verbose=verbose,
    )


def find_transfers_content_anchor(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
    nav: dict,
) -> OcrHit | None:
    """
    Якорь «Переводы» в контенте вкладки Платежи, не в нижнем таб-баре.
    OCR часто ловит «Переводы» на главной — такой hit отбрасываем по Y.
    """
    needle = str(nav["transfers"]).strip().lower()
    max_ratio = float(nav["transfers_max_y_ratio"])
    best: OcrHit | None = None
    for hit in hits:
        if needle not in hit.text.lower():
            continue
        if _hit_y_ratio(hit, region) > max_ratio:
            continue
        if best is None or hit.confidence > best.confidence:
            best = hit
    return best


def _carousel_band_signature(hits: list[OcrHit], transfers: OcrHit) -> frozenset[str]:
    min_y = transfers.y + 15
    max_y = transfers.y + 140
    return frozenset(
        h.text.strip().lower()
        for h in hits
        if min_y <= h.y <= max_y and h.text.strip()
    )


def wait_for_transfers_content_anchor(
    *,
    region: tuple[int, int, int, int],
    nav: dict,
    timeout_sec: float | None = None,
    poll_sec: float | None = None,
    verbose: bool = True,
) -> OcrHit:
    interval = poll_sec if poll_sec is not None else 0.45
    deadline = time.monotonic() + (
        timeout_sec if timeout_sec is not None else nav["timeout"]
    )
    while time.monotonic() < deadline:
        hits = scan_screen(region)
        anchor = find_transfers_content_anchor(hits, region, nav)
        if anchor is not None:
            if verbose:
                ratio = _hit_y_ratio(anchor, region)
                print(
                    f"[INFO] Якорь {nav['transfers']!r} в контенте "
                    f"→ ({anchor.x:.0f}, {anchor.y:.0f}), y={ratio:.0%}"
                )
            return anchor
        time.sleep(interval)

    raise BankNavError(
        f"Якорь {nav['transfers']!r} не появился на вкладке {nav['payments']!r} "
        f"за {timeout_sec or nav['timeout']:.0f} с"
    )


def _other_country_labels(cfg: dict) -> list[str]:
    raw = cfg["other_countries"]
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def find_other_countries_text(
    hits: list[OcrHit],
    labels: list[str],
    *,
    transfers: OcrHit | None = None,
) -> OcrHit | None:
    hit = find_labels(hits, labels, partial=True)
    if hit is not None:
        return hit

    if transfers is None:
        return None

    min_y = transfers.y - 10
    max_y = transfers.y + 130
    keywords = ("друг", "дру", "стра")
    candidates: list[OcrHit] = []
    for h in hits:
        if not (min_y <= h.y <= max_y):
            continue
        hay = h.text.lower()
        if any(k in hay for k in keywords):
            candidates.append(h)

    if not candidates:
        return None
    return max(candidates, key=lambda h: h.x)


def other_countries_tap_xy(
    hits: list[OcrHit],
    *,
    transfers: OcrHit,
    nav: dict | None = None,
) -> tuple[float, float, str]:
    """OCR «Друг стра» / «Другие страны» → тап по центру подписи."""
    nav = nav or _nav_cfg()
    bank = bank_settings()
    labels = _other_country_labels(nav)
    text_hit = find_other_countries_text(hits, labels, transfers=transfers)
    if text_hit is None:
        raise BankNavError("OCR не видит «Друг стра» на карусели")

    tap_on_text = bool(bank.get("other_tap_on_text", True))
    if tap_on_text:
        x = text_hit.x
        y = text_hit.y
    else:
        x = text_hit.x
        y = text_hit.y - nav["other_tap_icon_offset_y"]
    return x, y, text_hit.text


def _scroll_point_under_transfers(
    transfers: OcrHit,
    nav: dict,
) -> tuple[float, float]:
    """Точка scroll — под заголовком «Переводы» (от OCR-якоря)."""
    x = transfers.x + nav["carousel_scroll_x_offset"]
    y = transfers.y + nav["carousel_scroll_below_y"]
    return x, y


def other_countries_edge_tap_xy(
    transfers: OcrHit,
    region: tuple[int, int, int, int],
    nav: dict,
) -> tuple[float, float]:
    """Точка на видимом правом краю карточки «Другие страны»."""
    left, top, width, height = region
    x = left + width * float(nav["other_edge_x_ratio"])
    y = transfers.y + float(nav["other_edge_y_offset"])
    right_inset = max(1.0, float(nav["other_edge_right_inset"]))
    return (
        min(max(x, left + right_inset), left + width - right_inset),
        min(max(y, top + 8), top + height - 8),
    )


def scroll_under_transfers(
    transfers: OcrHit,
    *,
    attempt: int = 1,
    method: str | None = None,
    verbose: bool = True,
) -> str:
    """Крутим карусель под «Переводы». method=None → из config или auto по attempt."""
    nav = _nav_cfg()
    scroll_x, scroll_y = _scroll_point_under_transfers(transfers, nav)

    scroll_method = method or nav["carousel_scroll_method"]
    if scroll_method == "auto":
        scroll_method = _SCROLL_METHODS[(attempt - 1) % len(_SCROLL_METHODS)]

    pixels = nav["carousel_scroll_pixels"]

    if verbose:
        print(
            f"[INFO] Scroll под «Переводы» ({scroll_x:.0f}, {scroll_y:.0f}) "
            f"← ({transfers.x:.0f}, {transfers.y:.0f}), "
            f"method={scroll_method}, pixels={pixels}, pulses={nav['carousel_scroll_pulses']}"
        )
    used = scroll_carousel_horizontal(
        scroll_x,
        scroll_y,
        pixels=pixels,
        lines=nav["carousel_scroll_lines"],
        pulses=nav["carousel_scroll_pulses"],
        pulse_gap_sec=nav["carousel_scroll_pulse_gap"],
        method=scroll_method,
        swipe_length=nav["carousel_swipe_length"],
        refocus_mirror=True,
        mirror_focus_sec=nav["carousel_focus_sec"],
        pre_scroll_sec=nav["carousel_pre_scroll_sec"],
        verbose=verbose,
    )
    gap = nav["carousel_post_scroll_sec"]
    if gap > 0:
        time.sleep(gap)
    settle = nav["carousel_settle_sec"]
    if settle > 0:
        time.sleep(settle)
    return used


def find_other_countries_under_transfers(
    *,
    transfers: OcrHit,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
) -> tuple[float, float, str]:
    """
    Под «Переводы»: scroll карусели → OCR «Друг стра» → координаты тапа.
    Пока не нашли — крутим дальше (до carousel_scroll_max_rounds).
    """
    nav = _nav_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    rounds = nav["carousel_scroll_max_rounds"]
    scrolls_done = 0
    last_sig: frozenset[str] | None = None
    stuck_rounds = 0
    scroll_method = nav["carousel_scroll_method"]

    for attempt in range(1, rounds + 2):
        hits = scan_screen(capture)
        try:
            x, y, label = other_countries_tap_xy(hits, transfers=transfers, nav=nav)
            if verbose:
                if scrolls_done:
                    print(
                        f"[INFO] «{label}» найдена после {scrolls_done} scroll "
                        f"→ тап ({x:.0f}, {y:.0f})"
                    )
                else:
                    print(f"[INFO] «{label}» → тап ({x:.0f}, {y:.0f})")
            return x, y, label
        except BankNavError:
            if scrolls_done >= rounds:
                break

            sig = _carousel_band_signature(hits, transfers)
            if sig and sig == last_sig:
                stuck_rounds += 1
            else:
                stuck_rounds = 0
            last_sig = sig

            scrolls_done += 1
            if verbose:
                print(
                    f"[INFO] «Друг стра» не видна — scroll "
                    f"{scrolls_done}/{rounds}…"
                )

            method = scroll_method
            if scroll_method == "auto" or stuck_rounds >= 2:
                method = _SCROLL_METHODS[(scrolls_done - 1) % len(_SCROLL_METHODS)]
                if stuck_rounds >= 2 and verbose:
                    print(
                        f"[WARN] Карусель не сдвинулась — пробуем method={method!r}"
                    )

            scroll_under_transfers(
                transfers,
                attempt=scrolls_done,
                method=method,
                verbose=verbose,
            )

    raise BankNavError(
        f"«Друг стра» не найдена после {scrolls_done} scroll под «Переводы»"
    )


def wait_for_label(
    labels: str | list[str],
    *,
    region: tuple[int, int, int, int] | None = None,
    timeout_sec: float | None = None,
    partial: bool = True,
    verbose: bool = True,
    refocus_first: bool = False,
) -> OcrHit:
    nav = _nav_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    if refocus_first:
        from device.input_device import focus_iphone_mirror

        bank = bank_settings()
        focus_iphone_mirror(
            settle_sec=float(bank.get("bank_handoff_gui_focus_sec", 0.45))
        )

    deadline = time.monotonic() + (timeout_sec if timeout_sec is not None else nav["timeout"])
    needle = [labels] if isinstance(labels, str) else labels

    while time.monotonic() < deadline:
        hits = scan_screen(capture)
        hit = find_labels(hits, needle, partial=partial)
        if hit is not None:
            if verbose:
                print(f"[INFO] Найдено {hit.text!r} → ({hit.x:.0f}, {hit.y:.0f})")
            return hit
        time.sleep(0.25)

    raise BankNavError(
        f"Не найдено {needle!r} за {timeout_sec or nav['timeout']:.0f} с"
    )


def wait_for_payments_tab(
    region: tuple[int, int, int, int],
    nav: dict,
    *,
    timeout_sec: float | None = None,
    verbose: bool = True,
    refocus_first: bool = False,
) -> OcrHit:
    deadline = time.monotonic() + (
        timeout_sec if timeout_sec is not None else nav["timeout"]
    )
    if refocus_first:
        from device.input_device import focus_iphone_mirror

        bank = bank_settings()
        focus_iphone_mirror(
            settle_sec=float(bank.get("bank_handoff_gui_focus_sec", 0.45))
        )

    while time.monotonic() < deadline:
        hits = scan_screen(region)
        hit = find_payments_tab(hits, region, nav)
        if hit is not None:
            if verbose:
                ratio = _hit_y_ratio(hit, region)
                print(
                    f"[INFO] Найдено {hit.text!r} (таб) "
                    f"→ ({hit.x:.0f}, {hit.y:.0f}), y={ratio:.0%}"
                )
            return hit
        time.sleep(0.25)

    raise BankNavError(
        f"Не найдено {nav['payments']!r} за {timeout_sec or nav['timeout']:.0f} с"
    )


def run_stage2_payments(
    *,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
    initial_hits: list[OcrHit] | None = None,
    handoff_fast: bool = False,
) -> None:
    """
    Этап 2:
      1. Тап «Платежи» (всегда — иначе OCR «Переводы» на главной даёт ложный якорь)
      2. Ждём «Переводы» в контенте вкладки
      3. Scroll под «Переводы» → «Друг стра» → тап
    """
    nav = _nav_cfg()
    bank = bank_settings()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    if handoff_fast:
        post_tap_settle = float(bank.get("bank_handoff_nav_settle_sec", 0.35))
        transfers_poll = float(bank.get("bank_handoff_transfers_poll_sec", 0.18))
        step_gap = float(bank.get("bank_handoff_step_gap_sec", 0.15))
    else:
        post_tap_settle = nav["nav_post_tap_settle_sec"]
        transfers_poll = None
        step_gap = nav["nav_step_gap_sec"]

    if verbose:
        print("[INFO] Этап 2: Платежи → scroll под Переводы → Друг стра")

    hits = initial_hits
    if hits is None:
        hits = scan_screen(capture)

    if not should_tap_payments_tab(hits, capture, nav):
        if verbose:
            print("[INFO] Уже на вкладке Платежи (Переводы в контенте) — тап таба пропущен")
    else:
        use_fixed_tap = (
            nav["stage2_always_tap_payments"]
            and nav["payments_fixed_tap_enabled"]
        )
        if use_fixed_tap:
            payments = payments_tab_fallback_hit(capture, nav)
            if verbose:
                print(
                    f"[INFO] Быстрый тап {nav['payments']!r} по координате "
                    f"({payments.x:.0f}, {payments.y:.0f})"
                )
        else:
            payments = find_payments_tab(hits, capture, nav)
            if payments is None:
                if initial_hits is not None and verbose:
                    print("[INFO] «Платежи» нет на handoff-скане — свежий OCR…")
                hits = scan_screen(capture)
                payments = find_payments_tab(hits, capture, nav)
            if payments is None:
                if verbose:
                    print(f"[INFO] Ждём таб {nav['payments']!r}…")
                from ui.hooks import is_gui_mode

                try:
                    payments = wait_for_payments_tab(
                        capture,
                        nav,
                        timeout_sec=nav["payments_ocr_timeout_sec"],
                        verbose=verbose,
                        refocus_first=handoff_fast or is_gui_mode(),
                    )
                except BankNavError:
                    if not nav["payments_fixed_tap_enabled"]:
                        raise
                    payments = payments_tab_fallback_hit(capture, nav)
                    if verbose:
                        print(
                            f"[WARN] OCR не видит {nav['payments']!r} — "
                            f"используем координату нижнего таба "
                            f"({payments.x:.0f}, {payments.y:.0f})"
                        )

        ratio = _hit_y_ratio(payments, capture)
        if verbose:
            in_reg = hit_in_region(payments, capture)
            print(
                f"[INFO] Тап по {nav['payments']!r} "
                f"@ ({payments.x:.0f}, {payments.y:.0f}), "
                f"y={ratio:.0%}, in_region={in_reg}"
            )
        if not hit_in_region(payments, capture):
            raise BankNavError(
                f"«Платежи» вне экрана: ({payments.x:.0f}, {payments.y:.0f})"
            )

        tap_nav_target(
            payments.x,
            payments.y,
            verbose=verbose,
            label=nav["payments"],
        )

    if post_tap_settle > 0:
        time.sleep(post_tap_settle)
    elif step_gap > 0:
        time.sleep(step_gap)

    transfers = wait_for_transfers_content_anchor(
        region=capture,
        nav=nav,
        poll_sec=transfers_poll,
        verbose=verbose,
    )

    if step_gap > 0:
        time.sleep(step_gap)

    if nav["other_edge_tap_enabled"]:
        tx, ty = other_countries_edge_tap_xy(transfers, capture, nav)
        label = "Другие страны (видимый край)"
        if verbose:
            print(f"[INFO] Быстрый тап по краю «Другие страны» @ ({tx:.0f}, {ty:.0f})")
    else:
        tx, ty, label = find_other_countries_under_transfers(
            transfers=transfers,
            region=capture,
            verbose=verbose,
        )
    tap_nav_target(tx, ty, verbose=verbose, label=label)

    if verbose:
        print("[OK] Этап 2 выполнен")
