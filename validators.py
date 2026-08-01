"""Валидация полей сделки tzk."""

from __future__ import annotations

import re

from models import RowPreview, TzkDeal


class PanicError(Exception):
    """Критическое несоответствие данных — немедленная остановка."""


_AMOUNT_RE = re.compile(r"-?\s*([\d][\d\s,]*(?:\.\d+)?)\s*([A-Za-z]{3})?")
_PLACEHOLDER_AMOUNT_RE = re.compile(
    r"^(?:set\s+rate|loading|—|-|\.\.\.)$",
    re.I,
)


def parse_amount(raw: str) -> tuple[float, str]:
    text = raw.strip().replace("\u00a0", " ")
    if not text:
        raise PanicError("Сумма пустая")
    if _PLACEHOLDER_AMOUNT_RE.match(text):
        raise PanicError(f"Сумма ещё не загрузилась: {raw!r}")

    match = _AMOUNT_RE.search(text)
    if not match:
        raise PanicError(f"Не удалось разобрать сумму: {raw!r}")

    number_part = match.group(1).replace(" ", "").replace(",", "")
    if not number_part.replace(".", "", 1).isdigit():
        raise PanicError(f"Сумма содержит недопустимые символы: {raw!r}")

    value = float(number_part)
    if value <= 0:
        raise PanicError(f"Сумма должна быть > 0, получено: {value}")

    currency = (match.group(2) or "").upper()
    return value, currency


def parse_amount_value(raw: str) -> float:
    """Только число из строки суммы; валюта игнорируется."""
    value, _ = parse_amount(raw)
    return value


def is_parseable_amount(raw: str) -> bool:
    try:
        parse_amount(raw)
        return True
    except PanicError:
        return False


def amounts_match(left_raw: str, right_raw: str, *, tolerance: float = 0.01) -> bool:
    return abs(parse_amount_value(left_raw) - parse_amount_value(right_raw)) <= tolerance


def clean_account(raw: str, *, min_digits: int, max_digits: int) -> str:
    cleaned = re.sub(r"[\s\-–—\u00a0]", "", raw.strip())
    cleaned = "".join(ch for ch in cleaned if ch.isdigit())

    if not cleaned:
        raise PanicError(f"Номер счёта пустой после очистки: {raw!r}")
    if not min_digits <= len(cleaned) <= max_digits:
        raise PanicError(
            f"Номер счёта {cleaned!r}: длина {len(cleaned)} "
            f"(ожидается {min_digits}–{max_digits})"
        )
    return cleaned


def optional_clean_holder_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    return name if len(name) >= 2 else ""


_BANK_VOWELS = frozenset("aeiouyAEIOUY")
# Явно без Y/Z-диапазонов — иначе Y попадает в «согласные»
_LETTER_RUN_RE = re.compile(
    r"[aeiouyAEIOUY]+|(?:(?![aeiouyAEIOUY])[a-zA-Z])+|[^a-zA-Z]"
)


def _limit_letter_runs(word: str, *, max_run: int = 2) -> str:
    """
    Не больше max_run гласных или согласных подряд в одном слове.
    MKRTCHYAN → MKYAN, OOOO → OO.
    """
    if not word:
        return word

    parts = _LETTER_RUN_RE.findall(word)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part[0] in _BANK_VOWELS:
            out.append(part[:max_run])
        elif part[0].isalpha():
            out.append(part[:max_run])
        else:
            out.append(part)
    return "".join(out)


_AN_IN_WORD_RE = re.compile(r"an", re.I)


def _letters_only(word: str) -> str:
    return "".join(ch for ch in word if ch.isalpha())


def _is_letter_palindrome(word: str, *, min_len: int = 3) -> bool:
    """Палиндром по буквам (регистр не важен). ANNA, ABA — да; IVAN — нет."""
    letters = _letters_only(word).lower()
    if len(letters) < min_len:
        return False
    return letters == letters[::-1]


def _has_vowel_and_consonant(word: str) -> bool:
    letters = _letters_only(word)
    if not letters:
        return False
    has_vowel = any(ch in _BANK_VOWELS for ch in letters)
    has_consonant = any(ch.isalpha() and ch not in _BANK_VOWELS for ch in letters)
    return has_vowel and has_consonant


def _bank_name_part_ok(word: str) -> bool:
    """Часть ФИО: ≥2 буквы, есть гласная и согласная, не палиндром."""
    limited = _limit_letter_runs(word)
    if len(_letters_only(limited)) < 2:
        return False
    if not _has_vowel_and_consonant(limited):
        return False
    if _is_letter_palindrome(limited):
        return False
    return True


def _break_palindrome_word(word: str) -> str:
    """
    Activ Bank не пропускает палиндромы в ФИО.
    1) вырезать «an» (ANNA → NA)
    2) иначе убрать одну букву с конца (OTTO → OTT), не оставляя
       только гласные/только согласные
    3) иначе дописать N/A чтобы сломать симметрию
    """
    current = _limit_letter_runs(word)
    if not _is_letter_palindrome(current):
        return current

    candidates: list[str] = []

    match = _AN_IN_WORD_RE.search(current)
    if match:
        candidates.append(current[: match.start()] + current[match.end() :])

    letter_idxs = [i for i, ch in enumerate(current) if ch.isalpha()]
    for idx in reversed(letter_idxs):
        candidates.append(current[:idx] + current[idx + 1 :])

    upper = any(ch.isupper() for ch in current)
    for ch in (("N", "A") if upper else ("n", "a")):
        candidates.append(current + ch)
        if letter_idxs:
            mid = letter_idxs[len(letter_idxs) // 2]
            candidates.append(current[:mid] + ch + current[mid:])

    seen: set[str] = set()
    for cand in candidates:
        limited = _limit_letter_runs(cand)
        if not limited or limited in seen:
            continue
        seen.add(limited)
        if _bank_name_part_ok(limited):
            return limited

    return current


def _collapse_reduplication(word: str) -> str:
    """
    Повтор слога банк тоже режет: NANA → NA, NONO → NO, NANANA → NA.
    """
    if not word.isalpha() or len(word) < 4:
        return word

    lo = word.lower()

    if len(lo) % 2 == 0:
        half = len(lo) // 2
        if lo[:half] == lo[half:]:
            return word[:half]

    # один и тот же 2-буквенный слог несколько раз
    if len(lo) >= 4 and len(lo) % 2 == 0:
        unit = lo[:2]
        if unit * (len(lo) // 2) == lo:
            return word[:2]

    return word


def _sanitize_name_part(word: str) -> str:
    limited = _limit_letter_runs(word)
    broken = _break_palindrome_word(limited)
    return _collapse_reduplication(broken)


def sanitize_holder_name_for_bank(raw: str) -> str:
    """
    Activ Bank: UPPERCASE + не больше 2 гласных/согласных подряд
    + ломаем палиндромы (ANNA → NA, OTTO → OTT)
    + схлопываем повтор слога (NANA → NA, NONO → NO).
    Hardware-ввод жмёт Shift на заглавные.
    """
    name = " ".join((raw or "").split())
    if not name:
        return ""
    parts = (_sanitize_name_part(part) for part in name.split())
    trimmed = " ".join(p for p in parts if _letters_only(p))
    return trimmed.upper()


def normalize_payment_method(raw: str) -> str:
    text = (raw or "").strip().lower()
    if "wechat" in text or "weixin" in text:
        return "wechat"
    if "alipay" in text or "支付宝" in text:
        return "alipay"
    if "card" in text or "mc" in text:
        return "card"
    return text or "unknown"


def skip_reason_for_preview(
    amount_usdt_raw: str,
    *,
    min_amount: float | None = None,
    max_amount: float | None = None,
    min_tjs: float | None = None,
    max_tjs: float | None = None,
) -> str | None:
    """Фильтр входа по USDT из списка; остальной пайплайн не затрагивает."""
    lo = min_amount if min_amount is not None else min_tjs
    hi = max_amount if max_amount is not None else max_tjs
    if lo is None and hi is None:
        return None
    text = (amount_usdt_raw or "").strip()
    if not text:
        return "нет USDT в строке списка"
    amount = parse_amount_value(text)
    if lo is not None and amount < lo:
        return f"USDT {amount:g} < минимума {lo:g}"
    if hi is not None and amount > hi:
        return f"USDT {amount:g} > лимита {hi:g}"
    return None


def card_bin_digit(account_raw: str) -> str:
    """Первая цифра номера карты (4=Visa, 5=MC)."""
    digits = "".join(ch for ch in (account_raw or "") if ch.isdigit())
    return digits[0] if digits else ""


def skip_reason_for_card_brand(
    account_raw: str,
    *,
    allow_visa: bool = True,
    allow_mastercard: bool = True,
) -> str | None:
    """
    Фильтр бренда карты перед Accept.
    4… = Visa, 5… = Mastercard. Если оба выкл — пропускаем всё.
    """
    if allow_visa and allow_mastercard:
        return None
    if not allow_visa and not allow_mastercard:
        return "Visa и MC выключены в фильтре"
    digit = card_bin_digit(account_raw)
    if not digit:
        return "нет цифр в номере карты"
    if digit == "4":
        if not allow_visa:
            return "Visa (4…) выключена"
        return None
    if digit == "5":
        if not allow_mastercard:
            return "MC (5…) выключена"
        return None
    return f"карта начинается с {digit} (нужны 4=Visa / 5=MC)"


def session_requisites_key(account_raw: str, holder_raw: str) -> str:
    """Ключ «карта + ФИО» в рамках одного прогона Accept."""
    digits = "".join(ch for ch in (account_raw or "") if ch.isdigit())
    holder = " ".join((holder_raw or "").split()).casefold()
    return f"{digits}|{holder}"


def skip_reason_for_session_duplicate(
    account_raw: str,
    holder_raw: str,
    *,
    requisites_in_run: dict[str, int],
) -> str | None:
    """
    PlatCore не даёт принять вторую сделку с теми же реквизитами+именем,
    пока первая ещё в pending. В одной сессии — сразу skip.
    """
    digits = "".join(ch for ch in (account_raw or "") if ch.isdigit())
    if not digits:
        return None
    key = session_requisites_key(account_raw, holder_raw)
    prev = requisites_in_run.get(key)
    if prev is None:
        return None
    last4 = digits[-4:] if len(digits) >= 4 else digits
    holder = " ".join((holder_raw or "").split()) or "—"
    return f"уже в #{prev}: *{last4} / {holder} (pending)"


def deal_to_dict(deal: TzkDeal) -> dict:
    holder = deal.holder_name.strip()
    return {
        "order_id": deal.order_id or deal.task_id,
        "task_id": deal.task_id,
        "account": {
            "raw": deal.account_raw,
            "digits": deal.account_digits,
        },
        "holder_name": holder or None,
        "amount_check": {
            "value": deal.amount_check,
            "currency": deal.amount_check_currency or None,
        },
        "amount_input": {"value": deal.amount_tjs, "currency": "TJS"},
        "amount_verify": (
            {"value": deal.amount_usd, "currency": "USD"}
            if deal.amount_usd > 0
            else {"value": deal.amount_eur, "currency": "EUR"}
        ),
        "payment_method": normalize_payment_method(deal.payment_method),
    }


def preview_to_task_id(preview: RowPreview) -> str:
    return preview.fingerprint.replace("|", "_")[:80]
