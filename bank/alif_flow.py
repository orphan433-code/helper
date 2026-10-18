"""Оплата в приложении Alif. Activ сюда не заходит.

После сверки карты и USD скрипт ждёт «Оплатить», жмёт её, потом «На главную»,
снимает экран успеха и идёт дальше (закрытие, чек, генерация).
"""

from __future__ import annotations

import re
import time

from bank.form import (
    BankFormError,
    BankPostPaymentError,
    TransferFormData,
    find_expected_credit_amount_anywhere,
    format_tjs_input,
)
from bank.nav import BankNavError, wait_for_label
from bank.screen import scan_screen
from core.config import bank_settings
from core.logkit import info
from device.clicker import input_field_text, tap_after_ocr
from device.input_device import ime_done
from device.ocr import OcrHit

# True: после сверки карты и USD сами ждём «Оплатить» и жмём её.
ALIF_TAP_PAY = True

_FIELD_DY = 48.0


_LOOKALIKE = str.maketrans(
    {
        "h": "н",
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "y": "у",
        "k": "к",
        "t": "т",
        "x": "х",
        "m": "м",
        "r": "р",
        "u": "у",
    }
)


def _fold(text: str) -> str:
    return (text or "").casefold().translate(_LOOKALIKE)


_HINT_MARKERS = (
    "укаж",
    "латиниц",
    "паспорт",
    "отклон",
    "получател",
    "данн",
    "иначе",
    "перевод",
)


def _filled_name(text: str) -> str:
    """Текст в поле имени. Подпись «Имя» и подсказка паспорта — не значение."""
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    folded = raw.casefold()
    if any(mark in folded for mark in _HINT_MARKERS):
        return ""
    if _fold(raw).strip(" .:•") in {"имя", "фамилия", "продолжить"}:
        return ""
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", raw)
    if len(letters) < 2:
        return ""
    return raw


def _exact_label(hits: list[OcrHit], word: str) -> OcrHit | None:
    needle = _fold(word)
    found = [
        hit
        for hit in hits
        if _fold(hit.text).strip(" .:•") == needle
    ]
    if not found:
        return None
    return min(found, key=lambda hit: hit.y)


def _value_between(hits: list[OcrHit], y0: float, y1: float) -> str:
    parts: list[str] = []
    for hit in sorted(hits, key=lambda item: (item.y, item.x)):
        if hit.y <= y0 + 6 or hit.y >= y1 - 4:
            continue
        token = _filled_name(hit.text)
        if token:
            parts.append(token)
    return " ".join(parts)


def existing_recipient_names(hits: list[OcrHit]) -> tuple[str, str]:
    """Что уже стоит под «Имя» и «Фамилия». Пустая строка — поле пустое."""
    first_label = _exact_label(hits, "имя")
    last_label = _exact_label(hits, "фамилия")
    if first_label is None or last_label is None:
        return "", ""
    if last_label.y <= first_label.y:
        return "", ""
    cont = _exact_label(hits, "продолжить")
    last_end = cont.y if cont is not None and cont.y > last_label.y else last_label.y + 140
    return (
        _value_between(hits, first_label.y, last_label.y),
        _value_between(hits, last_label.y, last_end),
    )


def split_alif_name(raw: str) -> tuple[str, str]:
    """Два поля, порядок не важен. Одно слово кладём в оба."""
    parts = [part for part in (raw or "").split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _timeout() -> float:
    return float(bank_settings().get("form_timeout_sec", 30))


def _find_phrase(hits: list[OcrHit], phrase: str) -> OcrHit | None:
    """Фраза в одном боксе или двумя соседними словами («На» + «карту»)."""
    needle = _fold(phrase).strip()
    compact = needle.replace(" ", "")
    for hit in hits:
        hay = _fold(hit.text)
        if needle in hay or (compact and compact in hay.replace(" ", "")):
            return hit

    words = needle.split()
    if len(words) != 2:
        return None
    first, second = words
    for left in hits:
        if _fold(left.text).strip() != first:
            continue
        for right in hits:
            if right is left or _fold(right.text).strip() != second:
                continue
            line = max(left.height, right.height, 16.0)
            same_row = abs(left.y - right.y) <= line and 0 <= (right.x - left.x) <= line * 6
            stacked = (
                abs(left.x - right.x) <= max(left.width, right.width, line * 3)
                and 0 < (right.y - left.y) <= line * 4
            )
            if not same_row and not stacked:
                continue
            return OcrHit(
                text=phrase,
                confidence=min(left.confidence, right.confidence),
                x=(left.x + right.x) / 2,
                y=(left.y + right.y) / 2,
                width=max(left.width, right.width),
                height=abs(right.y - left.y) + max(left.height, right.height),
            )
    return None


def _find_card_tile(hits: list[OcrHit]) -> OcrHit | None:
    """Плитка «На карту». OCR часто не видит «На» и оставляет одно слово «карту».

    «Все карты» и «На Alif» — другие плитки, их не берём.
    """
    for hit in hits:
        if _fold(hit.text).strip(" .…") == "карту":
            return hit
    return _find_phrase(hits, "На карту")


def _bottom_tab(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
    label: str,
) -> OcrHit | None:
    _left, top, _width, height = region
    floor = top + height * 0.78
    needle = _fold(label)
    for hit in hits:
        if hit.y < floor:
            continue
        if needle in _fold(hit.text):
            return hit
    return None


def _ocr_preview(hits: list[OcrHit]) -> str:
    parts: list[str] = []
    for hit in sorted(hits, key=lambda item: (round(item.y / 16), item.x)):
        text = " ".join(hit.text.split())
        if not text or sum(ch.isdigit() for ch in text) >= 6:
            continue
        if text not in parts:
            parts.append(text)
        if len(parts) >= 40:
            break
    return ", ".join(parts) if parts else "пусто"


def _scan(region: tuple[int, int, int, int], *, low: bool) -> list[OcrHit]:
    if not low:
        return scan_screen(region)
    from device.ocr import run_ocr
    from device.screenshot import take_screenshot

    return run_ocr(
        take_screenshot(region=region),
        region=region,
        confidence_min=0.12,
    )


def _open_card_transfer(
    region: tuple[int, int, int, int],
    *,
    verbose: bool,
) -> None:
    """Плитка «На карту». Если её нет — вкладка «Главный», потом снова плитка."""
    deadline = time.monotonic() + _timeout()
    tried_home = False
    last: list[OcrHit] = []
    while time.monotonic() < deadline:
        for low in (False, True):
            last = _scan(region, low=low)
            if _find_phrase(last, "Номер карты получателя") is not None:
                info("Alif: уже экран номера карты")
                return
            hit = _find_card_tile(last)
            if hit is not None:
                tap_after_ocr(hit.x, hit.y, verbose=verbose, label="На карту")
                return
        if not tried_home:
            tried_home = True
            tab = _bottom_tab(last, region, "Главный")
            if tab is not None:
                info("Alif: «На карту» не видно, открываю «Главный»")
                tap_after_ocr(tab.x, tab.y, verbose=verbose, label="Главный")
                time.sleep(0.7)
                continue
        time.sleep(0.35)

    raise BankFormError(
        f"Не найдено «На карту». На экране: {_ocr_preview(last)}"
    )


def _tap(
    labels: str | list[str],
    region: tuple[int, int, int, int],
    *,
    dy: float = 0.0,
    verbose: bool = True,
) -> OcrHit:
    hit = wait_for_label(
        labels,
        region=region,
        timeout_sec=_timeout(),
        partial=True,
        verbose=verbose,
    )
    tap_after_ocr(hit.x, hit.y + dy, verbose=verbose, label=hit.text)
    return hit


def _type(value: str, *, method: str, label: str, verbose: bool) -> None:
    shown = value
    if label == "карта" and len(value) >= 4:
        shown = f"*{value[-4:]} ({len(value)} цифр)"
    if verbose:
        print(f"[INFO] Alif ввод {label}: {shown}")
    if method == "digits":
        from device.adb import type_digits_burst

        # 20 мс на телефоне между цифрами. Один adb на всю строку.
        type_digits_burst(value, gap_sec=0.02)
        gap = 0.05
    else:
        input_field_text(value, method=method, clear=False)
        gap = float(bank_settings().get("form_after_type_sec", 0.3))
    if gap > 0:
        time.sleep(gap)


def _wait_screen(
    labels: list[str],
    region: tuple[int, int, int, int],
    *,
    verbose: bool,
) -> OcrHit:
    try:
        return wait_for_label(
            labels,
            region=region,
            timeout_sec=_timeout(),
            partial=True,
            verbose=verbose,
        )
    except BankNavError as exc:
        raise BankFormError(str(exc)) from exc


def _screen_digits(hits: list[OcrHit]) -> str:
    ordered = sorted(hits, key=lambda hit: (round(hit.y / 12), hit.x))
    return re.sub(r"\D", "", "".join(hit.text for hit in ordered))


def _has_visa(text: str) -> bool:
    raw = (text or "").casefold()
    return "visa" in raw or "виза" in _fold(text)


def _short_label(hits: list[OcrHit], needle: str) -> OcrHit | None:
    found = [
        hit
        for hit in hits
        if needle in _fold(hit.text).strip(" .:")
        and len(hit.text) <= 16
    ]
    if not found:
        return None
    return min(found, key=lambda hit: hit.x)


def find_visa_pay_account(hits: list[OcrHit]) -> OcrHit | None:
    """Счёт Visa справа от «Моби» и «Бонус». Gold, Platinum и прочие — один блок."""
    mobi = _short_label(hits, "моби")
    bonus = _short_label(hits, "бонус")
    anchor = bonus or mobi
    visas = [hit for hit in hits if _has_visa(hit.text)]
    if not visas:
        return None
    if anchor is not None:
        row = [
            hit
            for hit in visas
            if hit.x > anchor.x + 8 and abs(hit.y - anchor.y) <= 120
        ]
        if row:
            return min(row, key=lambda hit: hit.x)
    return min(visas, key=lambda hit: (hit.y, hit.x))


def _find_amount_label(hits: list[OcrHit]) -> OcrHit | None:
    for hit in hits:
        hay = hit.text.strip().lower()
        if hay == "сумма":
            return hit
    for hit in hits:
        hay = hit.text.lower()
        if "сумма" not in hay:
            continue
        if any(skip in hay for skip in ("зачисл", "списан", "итого", "конверт")):
            continue
        return hit
    return None


_AMOUNT_RE = re.compile(
    r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
)
_CURRENCY_RE = re.compile(r"(?:^|\s)(?:с\.?|tjs|сомон\w*)(?:\s|$)")


def _amount_tokens(text: str) -> list[float]:
    values: list[float] = []
    for match in _AMOUNT_RE.finditer(text):
        raw = (
            match.group(0)
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
        )
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", raw):
            values.append(float(raw.replace(".", "").replace(",", ".")))
            continue
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
            values.append(float(raw.replace(".", "")))
            continue
        if "," in raw and "." not in raw:
            values.append(float(raw.replace(",", ".")))
            continue
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def _close_to_expected(actual: float, expected: float, tolerance: float) -> bool:
    from bank.form import _reconcile_eur_ocr

    got = _reconcile_eur_ocr(actual, expected, tolerance)
    if abs(got - expected) <= max(tolerance, 0.011):
        return True
    # «7811» вместо «7811,09» — копейки не прочитались.
    if float(int(actual)) == actual and abs(actual - expected) < 0.2:
        return True
    return False


def _row_is_somoni(text: str) -> bool:
    folded = _fold(text)
    if any(skip in folded for skip in ("комис", "итого", "%")):
        return False
    return _CURRENCY_RE.search(folded) is not None or "сумм" in folded


def _confirm_has_somoni(
    hits: list[OcrHit],
    expected: float,
    tolerance: float,
) -> bool:
    """Строка введённых сомони. Комиссию и «Итого» не считаем.

    «7 811,09 с.» OCR режет на куски, «с» пишет латиницей, тысячи — точкой.
    """
    if expected <= 0:
        return False
    seen: list[float] = []
    for hit in hits:
        if any(abs(hit.y - y) <= 8 for y in seen):
            continue
        seen.append(hit.y)
        near = [item for item in hits if abs(item.y - hit.y) <= 40]
        row = " ".join(item.text for item in sorted(near, key=lambda item: item.x))
        if not _row_is_somoni(row):
            continue
        for value in _amount_tokens(row):
            if _close_to_expected(value, expected, tolerance):
                return True
    return False


def _amount_preview(hits: list[OcrHit]) -> str:
    parts: list[str] = []
    for hit in sorted(hits, key=lambda item: (item.y, item.x)):
        text = " ".join(hit.text.split())
        if not re.search(r"\d", text):
            continue
        if sum(ch.isdigit() for ch in text) >= 8:
            continue
        if text not in parts:
            parts.append(text)
        if len(parts) >= 8:
            break
    return ", ".join(parts) if parts else "чисел не вижу"


def _verify_confirm(
    hits: list[OcrHit],
    data: TransferFormData,
) -> None:
    """Экран «Оплатить»: карта и сумма к зачислению. Имя здесь не сверяем."""
    account = re.sub(r"\D", "", data.account)
    digits = _screen_digits(hits)
    if len(account) >= 8 and account not in digits:
        if not (account[:4] in digits and account[-4:] in digits):
            raise BankFormError(
                f"На подтверждении нет карты *{account[-4:]}"
            )

    tolerance = float(bank_settings().get("eur_verify_tolerance", 0.01))
    if data.amount_usd is None or data.amount_usd <= 0:
        raise BankFormError(
            "Alif: в сделке нет USD, сверку долларов не пропускаем"
        )

    found = find_expected_credit_amount_anywhere(
        hits,
        data.amount_usd,
        "USD",
        tolerance,
    )
    if found is None:
        raise BankFormError(
            f"На подтверждении нет {data.amount_usd:g} USD "
            f"(Сумма к зачислению). На экране: {_amount_preview(hits)}"
        )
    info(f"Alif сверка USD: {found:g} ≈ {data.amount_usd:g}")


def _find_alif_home(
    hits: list[OcrHit],
    region: tuple[int, int, int, int],
) -> OcrHit | None:
    """Кнопка «На главную» после оплаты. Вкладку «Главный» не берём.

    Пока на экране «Подтвердите» — это ещё не успех, даже если OCR
    зацепил похожее слово.
    """
    folded = [_fold(hit.text) for hit in hits]
    if any("подтверд" in text for text in folded):
        return None
    _left, top, _width, height = region
    floor = top + height * 0.45
    found = [hit for hit in hits if "главную" in _fold(hit.text)]
    if not found:
        return None
    low = [hit for hit in found if hit.y >= floor]
    return max(low or found, key=lambda hit: hit.y)


def _payment_left_the_form(hits: list[OcrHit]) -> bool:
    blob = " ".join(_fold(hit.text) for hit in hits)
    return "отправлен" in blob or "исполнен" in blob or "главную" in blob


def _finish_after_pay(
    region: tuple[int, int, int, int],
    *,
    verbose: bool,
) -> None:
    """Дождаться «На главную», снять скрин успеха, нажать и выйти на главную."""
    if ALIF_TAP_PAY:
        info("Alif: жду «Оплатить»")
        _tap(["Оплатить"], region, verbose=verbose)
    else:
        info(
            "Alif: жми «Оплатить» сам. "
            "Дальше жду «На главную» — скрин, домой, закрытие сделки"
        )

    wait_sec = max(180.0, float(bank_settings().get("success_timeout_sec", 60)))
    deadline = time.monotonic() + wait_sec
    sent = False
    btn: OcrHit | None = None
    while time.monotonic() < deadline:
        hits = scan_screen(region)
        if _payment_left_the_form(hits):
            sent = True
        btn = _find_alif_home(hits, region)
        if btn is not None:
            break
        time.sleep(0.5)
    else:
        if sent:
            raise BankPostPaymentError(
                "Alif: платёж уже ушёл, кнопку домой не нашёл. "
                "Повтор перевода не делай"
            )
        raise BankFormError(
            "Alif: не дождался экрана после оплаты. "
            "Если «Оплатить» не нажата — можно повтор"
        )

    assert btn is not None
    try:
        from completion.proof import save_success_proof_before_home

        save_success_proof_before_home()
        refreshed = _find_alif_home(scan_screen(region), region)
        if refreshed is not None:
            btn = refreshed
    except Exception as exc:
        info(f"Alif: скрин успеха не сохранился: {exc}")

    tap_after_ocr(btn.x, btn.y, verbose=verbose, label="На главную")
    info("Alif: на главной. Дальше чек, генерация и закрытие")


def run_alif_transfer(
    data: TransferFormData,
    *,
    region: tuple[int, int, int, int],
    verbose: bool = True,
) -> None:
    """Главная → карта → счёт Visa → сумма → имя → подтверждение.

    После сверки карты и USD скрипт ждёт кнопку «Оплатить» и жмёт её.
    """
    first, last = split_alif_name(data.holder_name)
    if not first or not last:
        raise BankFormError("Alif: пустое имя получателя")

    amount_text = format_tjs_input(data.amount_tjs, decimal=",")
    info(
        f"Alif: *{data.account[-4:]} | {amount_text} с. | {first} / {last}"
    )

    _open_card_transfer(region, verbose=verbose)

    _tap(
        ["Номер карты получателя", "xxxx"],
        region,
        dy=_FIELD_DY,
        verbose=verbose,
    )
    _type(re.sub(r"\D", "", data.account), method="digits", label="карта", verbose=verbose)
    info("Alif: карта введена, ждём экран счёта")
    _wait_screen(
        ["Оплата со сч", "Моби", "Бонус", "Visa"],
        region,
        verbose=verbose,
    )
    account_hits = scan_screen(region)
    visa = find_visa_pay_account(account_hits)
    if visa is None:
        raise BankFormError(
            f"Alif: нет счёта Visa после «Моби» и «Бонус». "
            f"На экране: {_ocr_preview(account_hits)}"
        )
    tap_after_ocr(visa.x, visa.y, verbose=verbose, label=visa.text)
    time.sleep(0.15)

    if (data.fiat_currency or "").strip().upper() == "KZT":
        info("Alif: сделка KZT, жму USD")
        _tap(["USD"], region, verbose=verbose)
        time.sleep(0.12)

    hits = scan_screen(region)
    amount_hit = _find_amount_label(hits)
    if amount_hit is None:
        amount_hit = _wait_screen(["Сумма"], region, verbose=verbose)
    tap_after_ocr(
        amount_hit.x,
        amount_hit.y + _FIELD_DY,
        verbose=verbose,
        label="Сумма",
    )
    time.sleep(0.2)
    _type(amount_text, method="digits", label="сумма", verbose=verbose)
    ime_done(settle_sec=0.25, verbose=verbose)

    _tap(["Продолжить"], region, verbose=verbose)
    _wait_screen(["Данные получателя", "Имя"], region, verbose=verbose)
    seen_first, seen_last = existing_recipient_names(scan_screen(region))
    if seen_first and seen_last:
        info("Alif: имя и фамилия уже стоят, не переписываю")
    else:
        if seen_first:
            info("Alif: имя уже стоит, не трогаю")
        else:
            _tap(["Имя"], region, dy=_FIELD_DY, verbose=verbose)
            _type(first, method="hardware", label="имя", verbose=verbose)
            ime_done(settle_sec=0.25, verbose=verbose)
        if seen_last:
            info("Alif: фамилия уже стоит, не трогаю")
        else:
            _tap(["Фамилия"], region, dy=_FIELD_DY, verbose=verbose)
            _type(last, method="hardware", label="фамилия", verbose=verbose)
            ime_done(settle_sec=0.35, verbose=verbose)

    _tap(["Продолжить"], region, verbose=verbose)
    _wait_screen(["Подтвердите перевод"], region, verbose=verbose)
    deadline = time.monotonic() + 8
    last_error: BankFormError | None = None
    while time.monotonic() < deadline:
        time.sleep(0.4)
        try:
            _verify_confirm(scan_screen(region), data)
            break
        except BankFormError as exc:
            text = str(exc)
            if "карты" in text or "нет USD" in text:
                raise
            last_error = exc
    else:
        assert last_error is not None
        raise last_error
    info("Alif: подтверждение сошлось")
    _finish_after_pay(region, verbose=verbose)
