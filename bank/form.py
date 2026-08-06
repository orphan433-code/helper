"""Bank flow — этап 3: форма перевода (карта, ФИО, сумма TJS, сверка EUR)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from bank.nav import wait_for_label
from bank.pin import PinUnlockError
from bank.screen import find_labels, scan_screen
from device.clicker import input_field_text, tap_after_ocr
from core.config import bank_settings, capture_region_or_raise
from device.input_device import dismiss_keyboard, ime_done, ime_next, tap_keyboard_globe
from device.ocr import OcrHit
from core.validators import sanitize_holder_name_for_bank


class BankFormError(RuntimeError):
    pass


class BankPostPaymentError(BankFormError):
    """Оплата уже ушла; упали на пост-шаге (обычно «На главную»).

    Повтор всего bank flow опасен — двойная оплата.
    """

    pass


@dataclass(frozen=True)
class TransferFormData:
    account: str
    holder_name: str
    amount_tjs: float
    amount_eur: float | None = None
    amount_usd: float | None = None


def format_tjs_input(amount: float, *, decimal: str = ".") -> str:
    """Только число для поля суммы, напр. 644.87 или 644,87."""
    raw = f"{amount:.2f}"
    if decimal == ",":
        return raw.replace(".", ",")
    return raw


def _labels(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _form_cfg() -> dict:
    bank = bank_settings()
    return {
        "by_card": _labels(bank.get("label_by_card") or ["По номеру карты", "номеру карты"]),
        "card_number": _labels(
            bank.get("label_card_number") or ["Введите номер карты", "номер карты"]
        ),
        "holder_name": _labels(
            bank.get("label_holder_name")
            or ["Введите Фамилию и Имя", "Введите фамилию", "фамилию имя"]
        ),
        "debit_section": _labels(bank.get("label_debit_section") or ["Сумма списания"]),
        "credit_section": _labels(bank.get("label_credit_section") or ["Сумма зачисления"]),
        "transfer_button": _labels(
            bank.get("label_transfer_button")
            or ["Продолжить", "Перевести"]
        ),
        # Android Activ: после суммы списания EUR появляется сам — без 1-го клика.
        "wait_credit_before_continue": bool(
            bank.get("wait_credit_before_continue", True)
        ),
        "continue_after_credit_only": bool(
            bank.get("continue_after_credit_only", True)
        ),
        "debit_amount_placeholder": _labels(
            bank.get("label_debit_amount_field") or ["Сумма"]
        ),
        "eur_verify_enabled": bool(bank.get("eur_verify_enabled", True)),
        "eur_verify_timeout_sec": float(bank.get("eur_verify_timeout_sec", 30)),
        "eur_verify_tolerance": float(bank.get("eur_verify_tolerance", 0.01)),
        "eur_verify_poll_sec": float(bank.get("eur_verify_poll_sec", 0.5)),
        "form_post_transfer_sec": float(bank.get("form_post_transfer_sec", 1.0)),
        "field_offset_y": float(bank.get("form_field_offset_y", 0)),
        "field_offset_x": float(bank.get("form_field_offset_x", 0)),
        "mirror_focus_sec": float(bank.get("mirror_focus_sec", 0.45)),
        "form_pre_tap_sec": float(bank.get("form_pre_tap_sec", 0.35)),
        "form_after_type_sec": float(bank.get("form_after_type_sec", 0.3)),
        "form_step_gap_sec": float(bank.get("form_step_gap_sec", 0.15)),
        "form_paste_settle_sec": float(bank.get("form_paste_settle_sec", 0.25)),
        "form_keyboard_switch_sec": float(bank.get("form_keyboard_switch_sec", 0.45)),
        "form_key_interval": float(bank.get("form_key_interval", 0.04)),
        "form_input_method": str(bank.get("form_input_method", "hardware")),
        "form_card_input_method": str(bank.get("form_card_input_method", "hardware")),
        "form_name_input_method": str(bank.get("form_name_input_method", "paste")),
        # text = adb input text (после паузы на numeric IME). digits = keyevent.
        "form_amount_input_method": str(
            bank.get("form_amount_input_method", "text")
        ),
        "form_amount_decimal": str(bank.get("form_amount_decimal", ".")),
        "keyboard_globe_taps": int(bank.get("keyboard_globe_taps", 2)),
        "form_timeout_sec": float(bank.get("form_timeout_sec", 30)),
        "form_input_retries": int(bank.get("form_input_retries", 1)),
        "fast_mode": bool(bank.get("fast_mode", False)),
        "form_burst_fill": bool(bank.get("form_burst_fill", True)),
        "form_between_fields_refocus": bool(
            bank.get("form_between_fields_refocus", False)
        ),
        "form_screen_settle_sec": float(bank.get("form_screen_settle_sec", 0.35)),
        "form_followup_pre_tap_sec": float(bank.get("form_followup_pre_tap_sec", 0.06)),
        "form_field_poll_sec": float(bank.get("form_field_poll_sec", 0.22)),
        # После ввода: IME «Далее» / галочка вместо тапа по следующему полю.
        "form_ime_chain": bool(bank.get("form_ime_chain", True)),
        "form_ime_next_sec": float(bank.get("form_ime_next_sec", 0.25)),
        "form_ime_done_sec": float(bank.get("form_ime_done_sec", 0.35)),
        # Пауза после Enter на сумму: пока Gboard переключится на цифры.
        "form_ime_amount_settle_sec": float(
            bank.get("form_ime_amount_settle_sec", 0.75)
        ),
    }


def transfer_data_from_config() -> TransferFormData | None:
    bank = bank_settings()
    account = str(bank.get("transfer_account") or "").strip()
    holder = str(bank.get("transfer_holder") or "").strip()
    amount = bank.get("transfer_amount_tjs")
    amount_eur = bank.get("transfer_amount_eur")
    if not account or not holder or amount in (None, "", 0):
        return None
    eur = float(amount_eur) if amount_eur not in (None, "") else None
    return TransferFormData(
        account=account,
        holder_name=sanitize_holder_name_for_bank(holder),
        amount_tjs=float(amount),
        amount_eur=eur,
    )


def find_debit_amount_field(hits: list[OcrHit], cfg: dict) -> OcrHit:
    """
    Поле «Сумма» под заголовком «Сумма списания» (не сам заголовок и не зачисление).
    """
    section = find_labels(hits, cfg["debit_section"], partial=True)
    if section is None:
        raise BankFormError("OCR не видит «Сумма списания»")

    credit = find_labels(hits, cfg["credit_section"], partial=True)
    y_max = credit.y - 8 if credit else section.y + 100

    best: OcrHit | None = None
    for hit in hits:
        hay = hit.text.strip().lower()
        if "списания" in hay or "зачисления" in hay:
            continue
        if hay != "сумма" and not any(
            ph.lower() == hay for ph in cfg["debit_amount_placeholder"]
        ):
            continue
        if section.y + 8 < hit.y < y_max:
            if best is None or hit.y < best.y:
                best = hit

    if best is not None:
        return best

    raise BankFormError(
        "OCR не видит placeholder «Сумма» под «Сумма списания» "
        f"(якорь @ {section.x:.0f}, {section.y:.0f})"
    )


def _try_find_debit_amount_field(hits: list[OcrHit], cfg: dict) -> OcrHit | None:
    try:
        return find_debit_amount_field(hits, cfg)
    except BankFormError:
        return None


def wait_for_transfer_form_fields(
    region: tuple[int, int, int, int],
    cfg: dict,
    *,
    verbose: bool = True,
) -> tuple[OcrHit, OcrHit, OcrHit]:
    """Один экран — ждём карту, ФИО и сумму на одном OCR-скане."""
    deadline = time.monotonic() + cfg["form_timeout_sec"]
    poll = cfg["form_field_poll_sec"]
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        hits = scan_screen(region)
        card = find_labels(hits, cfg["card_number"], partial=True)
        holder = find_labels(hits, cfg["holder_name"], partial=True)
        amount = _try_find_debit_amount_field(hits, cfg)
        if card is not None and holder is not None and amount is not None:
            if verbose:
                print(
                    "[INFO] Форма (1 скан): "
                    f"карта @ ({card.x:.0f},{card.y:.0f}), "
                    f"ФИО @ ({holder.x:.0f},{holder.y:.0f}), "
                    f"сумма @ ({amount.x:.0f},{amount.y:.0f})"
                )
            return card, holder, amount
        if verbose and attempt % max(1, int(1.5 / poll)) == 1:
            left = int(deadline - time.monotonic())
            print(f"    … ждём поля формы (~{left}s)")
        time.sleep(poll)

    raise BankFormError(
        "Не все поля формы видны за отведённое время "
        "(карта / ФИО / сумма списания)"
    )


_EUR_NOISE = re.compile(r"^(?:сумма|tjs|usd|комиссия)$", re.I)


def _parse_credit_number_loose(raw: str) -> float | None:
    """
    Парсит EUR из OCR. Activ Bank: «49,81» (запятая — десятичный разделитель).
    """
    text = raw.strip().replace("\u00a0", " ")
    if not text or _EUR_NOISE.match(text):
        return None
    if re.fullmatch(r"(?:EUR|€)", text, re.I):
        return None

    text = re.sub(r"(?:EUR|€)", "", text, flags=re.I).strip()
    match = re.search(r"[\d\s.,]+", text)
    if not match:
        return None
    num = match.group(0).replace(" ", "")

    # 1.234,56 — тысячи через точку, копейки через запятую
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", num):
        return float(num.replace(".", "").replace(",", "."))

    # 49,81 — десятичная запятая (типично для банка)
    if re.fullmatch(r"\d+,\d{2}", num):
        return float(num.replace(",", "."))

    # 49.81 — десятичная точка
    if re.fullmatch(r"\d+\.\d{1,2}", num):
        return float(num)

    # Целое без разделителя (OCR мог не увидеть «,» или «.»)
    if re.fullmatch(r"\d+", num):
        return float(num)

    return None


def _parse_eur_number_loose(raw: str) -> float | None:
    return _parse_credit_number_loose(raw)


def _parse_eur_value(raw: str) -> float | None:
    value = _parse_credit_number_loose(raw)
    if value is None or value <= 0:
        return None
    # Отсечь TJS/другие валюты, если в строке явно не EUR
    hay = raw.lower()
    if any(cur in hay for cur in ("tjs", "usd", "gel", "rub")):
        return None
    return value


def _reconcile_eur_ocr(actual: float, expected: float, tolerance: float) -> float:
    """
    OCR часто не видит десятичный разделитель: 49,81 → «4981».
    Если expected известен — пробуем /10, /100, /1000 и вставку точки по масштабу.
    """
    tol = max(tolerance, 0.011)

    if abs(actual - expected) <= tol:
        return actual

    for divisor in (100, 10, 1000):
        scaled = actual / divisor
        if abs(scaled - expected) <= tol:
            return scaled

    # 4981 + expected 49.81 → вставить точку за 2 знака
    if expected > 0 and float(int(actual)) == actual:
        decimals = 2
        s = str(int(actual))
        if len(s) > decimals:
            candidate = float(f"{s[:-decimals]}.{s[-decimals:]}")
            if abs(candidate - expected) <= tol:
                return candidate

    return actual


def _credit_section_bounds(hits: list[OcrHit], cfg: dict) -> tuple[OcrHit, float, float]:
    section = find_labels(hits, cfg["credit_section"], partial=True)
    if section is None:
        raise BankFormError("OCR не видит «Сумма зачисления»")

    transfer = find_labels(hits, cfg["transfer_button"], partial=True)
    y_min = section.y + 8
    y_max = transfer.y - 12 if transfer else section.y + 100
    return section, y_min, y_max


def find_transfer_button(hits: list[OcrHit], cfg: dict) -> OcrHit:
    hit = find_labels(hits, cfg["transfer_button"], partial=True)
    if hit is not None:
        return hit
    raise BankFormError(f"OCR не видит кнопку {cfg['transfer_button']!r}")


def _parse_usd_value(raw: str) -> float | None:
    value = _parse_credit_number_loose(raw)
    if value is None or value <= 0:
        return None
    hay = raw.lower()
    if any(cur in hay for cur in ("tjs", "eur", "gel", "rub", "thb", "€")):
        return None
    return value


def read_credit_amount(
    hits: list[OcrHit],
    cfg: dict,
    currency: str,
) -> float | None:
    """OCR «Сумма зачисления» — EUR или USD."""
    try:
        _section, y_min, y_max = _credit_section_bounds(hits, cfg)
    except BankFormError:
        return None

    in_band = [h for h in hits if y_min <= h.y <= y_max]
    parser = _parse_usd_value if currency == "USD" else _parse_eur_value
    marker_re = re.compile(r"\bUSD\b", re.I) if currency == "USD" else re.compile(
        r"\bEUR\b|€", re.I
    )

    for hit in in_band:
        value = parser(hit.text)
        if value is not None and marker_re.search(hit.text):
            return value

    marks = [h for h in in_band if marker_re.search(h.text)]
    for mark in marks:
        row = [h for h in in_band if abs(h.y - mark.y) <= 18 and h.x <= mark.x + 8]
        for hit in sorted(row, key=lambda h: -h.x):
            value = parser(hit.text)
            if value is not None:
                return value

    for hit in in_band:
        value = parser(hit.text)
        if value is not None:
            return value

    if currency == "USD":
        for hit in in_band:
            value = _parse_credit_number_loose(hit.text)
            if value is not None and value > 0:
                return value

    return None


def read_credit_eur_amount(hits: list[OcrHit], cfg: dict) -> float | None:
    return read_credit_amount(hits, cfg, "EUR")


def find_expected_credit_amount_anywhere(
    hits: list[OcrHit],
    expected: float,
    currency: str,
    tolerance: float,
) -> float | None:
    """
    Найти ожидаемую сумму в строке нужной валюты без привязки к заголовку.

    Поддерживает EUR и USD и склеивает OCR-фрагменты одной строки:
    например, «101,» + «56» + «EUR».
    """
    currency = currency.upper()
    if currency == "EUR":
        marker_re = re.compile(r"\bEUR\b|€", re.I)
        parser = _parse_eur_value
    elif currency == "USD":
        marker_re = re.compile(r"\bUSD\b|\$", re.I)
        parser = _parse_usd_value
    else:
        return None

    for marker in hits:
        if not marker_re.search(marker.text):
            continue
        row = [hit for hit in hits if abs(hit.y - marker.y) <= 18]
        joined = " ".join(hit.text for hit in sorted(row, key=lambda hit: hit.x))
        actual = parser(joined)
        if actual is None:
            continue
        reconciled = _reconcile_eur_ocr(actual, expected, tolerance)
        if abs(reconciled - expected) <= tolerance:
            return reconciled
    return None


def wait_for_credit_amount(
    expected: float,
    currency: str,
    *,
    region: tuple[int, int, int, int],
    cfg: dict,
    verbose: bool = True,
) -> float:
    deadline = time.monotonic() + cfg["eur_verify_timeout_sec"]
    tolerance = cfg["eur_verify_tolerance"]
    poll = cfg["eur_verify_poll_sec"]
    last_raw: float | None = None
    last_reconciled: float | None = None

    while time.monotonic() < deadline:
        hits = scan_screen(region)
        expected_actual = find_expected_credit_amount_anywhere(
            hits,
            expected,
            currency,
            tolerance,
        )
        if expected_actual is not None:
            if verbose:
                print(
                    f"[OK] {currency} сверка: {expected_actual:g} ≈ {expected:g} "
                    "— найдено по строке валюты"
                )
            return expected_actual

        raw_actual = read_credit_amount(hits, cfg, currency)
        if raw_actual is not None:
            last_raw = raw_actual
            actual = _reconcile_eur_ocr(raw_actual, expected, tolerance)
            last_reconciled = actual
            if abs(actual - expected) <= tolerance:
                if verbose:
                    note = ""
                    if abs(raw_actual - actual) > tolerance:
                        note = f" (OCR {raw_actual:g} → {actual:g})"
                    print(
                        f"[OK] {currency} сверка: {actual:g} ≈ {expected:g}{note} "
                        "— можно жать «Продолжить»"
                    )
                return actual
            if verbose:
                print(
                    f"[INFO] OCR {raw_actual:g} → {actual:g}, "
                    f"ожидаем {expected:g} {currency} — ждём…"
                )
        time.sleep(poll)

    detail = ""
    if last_raw is not None:
        detail = f" (последний OCR: {last_raw:g}"
        if last_reconciled is not None and last_reconciled != last_raw:
            detail += f" → {last_reconciled:g}"
        detail += f", ожидалось {expected:g} {currency})"
    raise BankFormError(
        f"{currency} в «Сумма зачисления» не совпал за "
        f"{cfg['eur_verify_timeout_sec']:.0f} с{detail}"
    )


def wait_for_credit_eur_amount(
    expected_eur: float,
    *,
    region: tuple[int, int, int, int],
    cfg: dict,
    verbose: bool = True,
) -> float:
    return wait_for_credit_amount(
        expected_eur, "EUR", region=region, cfg=cfg, verbose=verbose
    )


def _tap_transfer_button(
    region: tuple[int, int, int, int],
    cfg: dict,
    *,
    verbose: bool,
    step: str,
) -> None:
    hits = scan_screen(region)
    btn = find_transfer_button(hits, cfg)
    if verbose:
        print(f"[INFO] {step}: тап «{btn.text}» @ ({btn.x:.0f}, {btn.y:.0f})")
    tap_after_ocr(
        btn.x,
        btn.y,
        verbose=verbose,
        label=btn.text,
    )


def _confirm_transfer(
    data: TransferFormData,
    *,
    region: tuple[int, int, int, int],
    cfg: dict,
    verbose: bool,
) -> bool:
    """
    Android Activ Bank:
      сумма списания → ждём авто «Сумма зачисления» (EUR/USD) → «Продолжить».

    Legacy (continue_after_credit_only=false):
      1-й «Перевести» → сверка → 2-й «Перевести».
    """
    from bank.confirm import _confirm_cfg

    post_cfg = _confirm_cfg()
    verify_usd = (
        data.amount_usd is not None
        and data.amount_usd > 0
        and cfg["eur_verify_enabled"]
    )
    verify_eur = (
        data.amount_eur is not None
        and data.amount_eur > 0
        and cfg["eur_verify_enabled"]
    )
    do_verify = verify_usd or verify_eur
    do_confirm = do_verify or post_cfg["post_transfer_enabled"]
    android_continue = bool(cfg.get("continue_after_credit_only", True))
    wait_credit_first = bool(cfg.get("wait_credit_before_continue", True))

    if not do_confirm:
        if verbose:
            print("[INFO] Подтверждение перевода пропущено")
        return False

    # Клаву уже закрыли ime_done на сумме; лишний dismiss не нужен.
    step_gap = cfg["form_step_gap_sec"]
    if step_gap > 0:
        time.sleep(step_gap)

    btn_name = cfg["transfer_button"][0] if cfg["transfer_button"] else "Продолжить"

    if android_continue:
        if verbose:
            if verify_usd:
                print(
                    f"[INFO] Этап 3b: ждём {data.amount_usd:g} USD в «Сумма зачисления» "
                    f"(авто после суммы списания) → «{btn_name}»"
                )
            elif verify_eur:
                print(
                    f"[INFO] Этап 3b: ждём {data.amount_eur:g} EUR в «Сумма зачисления» "
                    f"(авто после суммы списания) → «{btn_name}»"
                )
            else:
                print(
                    f"[INFO] Этап 3b: ждём «Сумма зачисления» → «{btn_name}»"
                )

        if wait_credit_first and verify_usd:
            wait_for_credit_amount(
                data.amount_usd,
                "USD",
                region=region,
                cfg=cfg,
                verbose=verbose,
            )
        elif wait_credit_first and verify_eur:
            wait_for_credit_amount(
                data.amount_eur,
                "EUR",
                region=region,
                cfg=cfg,
                verbose=verbose,
            )
        elif wait_credit_first:
            # Без ожидаемой суммы — ждём появления секции / кнопки.
            _wait_for_transfer_button(region, cfg, verbose=verbose)
        else:
            gap = cfg["form_post_transfer_sec"]
            if gap > 0:
                time.sleep(gap)

        # Сверка EUR/USD прошла — докручиваем до «Продолжить» (1 swipe).
        from device.input_adb import quick_scroll_form_down

        quick_scroll_form_down(verbose=verbose, pulses=1)

        _tap_transfer_button(
            region, cfg, verbose=verbose, step=f"«{btn_name}»",
        )
        if verbose:
            print(f"[OK] Этап 3b: «{btn_name}» — ждём экран подтверждения")
        return True

    # Legacy dual-tap
    if verbose:
        if verify_usd:
            print(
                f"[INFO] Этап 3b: «Перевести» → ждём {data.amount_usd:g} USD "
                f"→ снова «Перевести»"
            )
        elif verify_eur:
            print(
                f"[INFO] Этап 3b: «Перевести» → ждём {data.amount_eur:g} EUR "
                f"→ снова «Перевести»"
            )
        else:
            print("[INFO] Этап 3b: «Перевести» × 2")

    _tap_transfer_button(
        region, cfg, verbose=verbose, step="1-й «Перевести»",
    )
    gap = cfg["form_post_transfer_sec"]
    if gap > 0 and not do_verify:
        time.sleep(gap)
    if verify_usd:
        wait_for_credit_amount(
            data.amount_usd, "USD", region=region, cfg=cfg, verbose=verbose,
        )
    elif verify_eur:
        wait_for_credit_amount(
            data.amount_eur, "EUR", region=region, cfg=cfg, verbose=verbose,
        )
    _tap_transfer_button(
        region, cfg, verbose=verbose, step="2-й «Перевести»",
    )
    if verbose:
        print("[OK] Этап 3b: 2-й «Перевести» — ждём экран подтверждения")
    return True


def _wait_for_transfer_button(
    region: tuple[int, int, int, int],
    cfg: dict,
    *,
    verbose: bool,
) -> OcrHit:
    """Ждём кнопку «Продолжить» / «Перевести» после авто-расчёта зачисления."""
    timeout = float(cfg["eur_verify_timeout_sec"])
    poll = float(cfg.get("eur_verify_poll_sec", 0.5))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hits = scan_screen(region)
        hit = find_labels(hits, cfg["transfer_button"], partial=True)
        if hit is not None:
            if verbose:
                print(
                    f"[INFO] Кнопка «{hit.text}» на экране "
                    f"@ ({hit.x:.0f}, {hit.y:.0f})"
                )
            return hit
        time.sleep(poll)
    raise BankFormError(
        f"Кнопка {cfg['transfer_button']!r} не появилась за {timeout:.0f} с"
    )

def _type_value_only(
    value: str,
    *,
    cfg: dict,
    verbose: bool,
    method: str | None = None,
    label: str = "",
) -> bool | None:
    """Ввод в уже сфокусированное поле (без тапа)."""
    input_method = method or cfg["form_input_method"]
    interval = cfg["form_key_interval"]
    if input_method == "paste":
        paste_gap = cfg["form_paste_settle_sec"]
        if paste_gap > 0:
            time.sleep(paste_gap)
    tag = f" {label}" if label else ""
    if verbose:
        print(f"    ⌨ {input_method}{tag} {value!r} ({len(value)} симв.)")
    result = input_field_text(value, method=input_method, interval=interval, clear=False)
    gap = cfg["form_after_type_sec"]
    if gap > 0:
        from bank.human import sleep_jitter

        sleep_jitter(gap)
    return result


def _type_into_field(
    x: float,
    y: float,
    value: str,
    *,
    cfg: dict,
    verbose: bool,
    label: str,
    method: str | None = None,
    refocus: bool = True,
    pre_tap_sec: float | None = None,
) -> None:
    """Тап в поле + ввод (adb input text / paste)."""
    tap_after_ocr(
        x,
        y,
        refocus=refocus,
        pre_tap_sec=pre_tap_sec,
        verbose=verbose,
        label=label,
    )
    kb_gap = cfg["form_keyboard_switch_sec"]
    if kb_gap > 0:
        from bank.human import sleep_jitter

        sleep_jitter(kb_gap)
    _type_value_only(value, cfg=cfg, verbose=verbose, method=method, label=label)


def _fill_field(
    labels: str | list[str],
    value: str,
    *,
    region: tuple[int, int, int, int],
    cfg: dict,
    verbose: bool,
    method: str | None = None,
    refocus: bool = True,
) -> None:
    if not value:
        raise BankFormError(f"Пустое значение для поля {labels!r}")

    hit = wait_for_label(
        labels,
        region=region,
        timeout_sec=cfg["form_timeout_sec"],
        partial=True,
        verbose=verbose,
    )
    x = hit.x + cfg["field_offset_x"]
    y = hit.y + cfg["field_offset_y"]

    if verbose:
        print(
            f"[INFO] Поле {hit.text!r} @ ({hit.x:.0f}, {hit.y:.0f}) "
            f"→ тап ({x:.0f}, {y:.0f}), ввод {value!r}"
        )
    _type_into_field(
        x, y, value, cfg=cfg, verbose=verbose, label=hit.text, method=method,
        refocus=refocus,
    )


def _fill_field_hit(
    hit: OcrHit,
    value: str,
    *,
    cfg: dict,
    verbose: bool,
    method: str | None = None,
    refocus: bool = True,
    pre_tap_sec: float | None = None,
) -> None:
    x = hit.x + cfg["field_offset_x"]
    y = hit.y + cfg["field_offset_y"]
    if verbose:
        print(
            f"[INFO] Поле {hit.text!r} @ ({hit.x:.0f}, {hit.y:.0f}) "
            f"→ тап ({x:.0f}, {y:.0f}), ввод {value!r}"
        )
    _type_into_field(
        x,
        y,
        value,
        cfg=cfg,
        verbose=verbose,
        label=hit.text,
        method=method,
        refocus=refocus,
        pre_tap_sec=pre_tap_sec,
    )


def run_stage3_transfer_form(
    data: TransferFormData,
    *,
    region: tuple[int, int, int, int] | None = None,
    verbose: bool = True,
) -> None:
    """
    Этап 3:
      1. «По номеру карты»
      2. «Введите номер карты» → счёт
      3. «Введите фамилию имя» → ФИО
      4. placeholder «Сумма» под «Сумма списания» → TJS
      5. Ждём авто EUR в «Сумма зачисления» → «Продолжить»
      6. Подтверждение / SMS → «На главную страницу»
    """
    cfg = _form_cfg()
    capture = region if region is not None else capture_region_or_raise()
    if capture is None:
        raise PinUnlockError("capture_region не задан")

    amount_decimal = str(cfg.get("form_amount_decimal") or ".")
    if amount_decimal not in (".", ","):
        amount_decimal = "."
    amount_text = format_tjs_input(data.amount_tjs, decimal=amount_decimal)
    burst = cfg["form_burst_fill"]
    refocus_between = cfg["form_between_fields_refocus"]
    follow_pre_tap = cfg["form_followup_pre_tap_sec"]
    step_gap = cfg["form_step_gap_sec"]

    if verbose:
        print(
            "[INFO] Этап 3: По номеру карты → "
            f"счёт …{data.account[-4:]}, ФИО, {amount_text} TJS"
            + (" [burst: 1 OCR]" if burst else "")
        )

    by_card = wait_for_label(
        cfg["by_card"],
        region=capture,
        timeout_sec=cfg["form_timeout_sec"],
        partial=True,
        verbose=verbose,
    )
    tap_after_ocr(
        by_card.x,
        by_card.y,
        verbose=verbose,
        label=by_card.text,
    )
    screen_settle = cfg["form_screen_settle_sec"]
    if screen_settle > 0:
        time.sleep(screen_settle)

    ime_chain = bool(cfg.get("form_ime_chain", True))
    ime_gap = float(cfg.get("form_ime_next_sec", 0.25))
    amount_settle = float(cfg.get("form_ime_amount_settle_sec", 0.9))
    amount_method = str(cfg.get("form_amount_input_method") or "softkey").strip().lower()
    # Сумма в Activ — кастомная клава приложения; input text/keyevent не пишут.
    if amount_method in ("hardware", "paste", "type", "us", "text", "digits"):
        amount_method = "softkey"

    if ime_chain:
        # Карта/ФИО — input text. Сумма — тапы по кнопкам UI (uiautomator).
        if verbose:
            print(
                "[INFO] IME-цепочка: карта → Enter → ФИО → "
                f"пауза {amount_settle:g}с → сумма (UI focus + input text) → Done"
            )
            print(
                "[INFO] На сумме Gboard не видно в dump — "
                "тап по EditText «Сумма» (слева, не TJS) + adb input text."
            )
        card_hit = wait_for_label(
            cfg["card_number"],
            region=capture,
            timeout_sec=cfg["form_timeout_sec"],
            partial=True,
            verbose=verbose,
        )
        _fill_field_hit(
            card_hit,
            data.account,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_card_input_method"],
            refocus=refocus_between,
            pre_tap_sec=cfg["form_pre_tap_sec"],
        )
        ime_next(settle_sec=ime_gap, verbose=verbose)
        if verbose:
            print(f"[INFO] Enter → ФИО, ввод {data.holder_name!r}")
        _type_value_only(
            data.holder_name,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_name_input_method"],
            label="ФИО",
        )
        # На Enter после ФИО не жмём: у Activ Bank «Next» с поля ФИО ведёт
        # фокус на select_currency (дропдаун «TJS ▾»), а не на amountEditText —
        # проверено живым UI dump. Идём сразу на explicit UI-focus суммы.
        if verbose:
            print(
                f"[INFO] Пауза {amount_settle:g}с, "
                f"потом focus EditText «Сумма» (без Enter) + {amount_text!r}"
            )
        if amount_settle > 0:
            time.sleep(amount_settle)
        # Быстрый scroll формы вниз — поле «Сумма списания» точно в видимой
        # зоне (Gboard уже открыт и подрезал viewport снизу).
        from device.input_adb import quick_scroll_form_down

        quick_scroll_form_down(verbose=verbose)
        # Не OCR-тап «Сумма» (легко мазнуть в TJS) — только UI dump bounds.
        # used_keypad=True → in-app PIN-подобная клава (может быть Done/галочка);
        # False → Gboard/EditText, галочки в dump не бывает — сразу KEYCODE_ENTER,
        # без лишнего uiautomator dump в tap_soft_done (1-4с на TECNO).
        used_keypad = _type_value_only(
            amount_text,
            cfg=cfg,
            verbose=verbose,
            method="softkey",
            label="Сумма",
        )
        after = float(cfg.get("form_after_type_sec", 0.3))
        if after > 0:
            time.sleep(after)
        done_settle = float(cfg.get("form_ime_done_sec", 0.35))
        done_tapped = False
        if used_keypad:
            from device.softkey import tap_soft_done

            done_tapped = tap_soft_done(verbose=verbose, settle_sec=done_settle)
        if not done_tapped:
            if verbose:
                print("[INFO] softkey Done нет — KEYCODE_ENTER")
            ime_done(settle_sec=done_settle, verbose=verbose)
        # TEMP: скролл после суммы списания отключён — смотрим, хватит ли
        # скролла после сверки зачисления перед «Продолжить».
        if verbose:
            print("[INFO] Скролл после суммы списания пропущен (временно)")
    elif burst:
        card_hit, holder_hit, amount_hit = wait_for_transfer_form_fields(
            capture, cfg, verbose=verbose
        )
        _fill_field_hit(
            card_hit,
            data.account,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_card_input_method"],
            refocus=refocus_between,
            pre_tap_sec=cfg["form_pre_tap_sec"],
        )
        dismiss_keyboard(interval=step_gap or 0.04)
        if step_gap > 0:
            time.sleep(step_gap)
        tap_keyboard_globe(
            region=capture,
            taps=cfg["keyboard_globe_taps"],
            verbose=verbose,
        )
        _fill_field_hit(
            holder_hit,
            data.holder_name,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_name_input_method"],
            refocus=refocus_between,
            pre_tap_sec=follow_pre_tap,
        )
        _fill_field_hit(
            amount_hit,
            amount_text,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_amount_input_method"],
            refocus=refocus_between,
            pre_tap_sec=follow_pre_tap,
        )
        dismiss_keyboard(interval=step_gap or 0.04)
    else:
        if step_gap > 0:
            time.sleep(step_gap)
        _fill_field(
            cfg["card_number"],
            data.account,
            region=capture,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_card_input_method"],
            refocus=refocus_between,
        )
        dismiss_keyboard(interval=step_gap or 0.04)
        if step_gap > 0:
            time.sleep(step_gap)
        tap_keyboard_globe(
            region=capture,
            taps=cfg["keyboard_globe_taps"],
            verbose=verbose,
        )
        _fill_field(
            cfg["holder_name"],
            data.holder_name,
            region=capture,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_name_input_method"],
            refocus=refocus_between,
        )
        hits = scan_screen(capture)
        amount_hit = find_debit_amount_field(hits, cfg)
        _fill_field_hit(
            amount_hit,
            amount_text,
            cfg=cfg,
            verbose=verbose,
            method=cfg["form_amount_input_method"],
            refocus=refocus_between,
        )
        dismiss_keyboard(interval=step_gap or 0.04)

    if step_gap > 0:
        time.sleep(step_gap)
    confirmed = _confirm_transfer(data, region=capture, cfg=cfg, verbose=verbose)

    if confirmed:
        from bank.confirm import run_post_transfer_steps

        run_post_transfer_steps(
            region=capture,
            expected_eur=data.amount_eur,
            verbose=verbose,
        )

    if verbose:
        print("[OK] Этап 3 выполнен")
