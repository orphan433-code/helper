"""Чтение полей карточки PlatCore (TJS / EUR / счёт / имя)."""

from __future__ import annotations

import json
import re
import time

from playwright.async_api import Locator, Page

from models import TzkDeal
from validators import (
    PanicError,
    amounts_match,
    clean_account,
    is_parseable_amount,
    optional_clean_holder_name,
    parse_amount,
    parse_amount_value,
    preview_to_task_id,
)

# Подписи на карточке (div.css-vot4m, текст может быть во вложенном p.chakra-text).
OWNER_LABELS = (
    "Account owner",
    "External client name",
    "Recipient name",
    "Sender Name",
)
# Счёт: приоритет полей с цифрами. «Account» без цифр = имя (pre-accept drawer).
ACCOUNT_FIELD_LABELS = (
    "To",
    "External client ID",
    "Account number",
    "Account",
)
LABEL_I_GIVE = "I give"  # pre-accept: сверка со списком
LABEL_YOU_SEND = "You send"  # post-accept: сверка со списком (182 GEL)
LABEL_EUR = "I give (XE amount)"  # post-accept: OCR (старая вёрстка)
LABEL_EUR_ALIASES = ("I give (XE amount)", "XE amount")
LABEL_TJS = "Activ to MC"  # legacy
LABEL_TJS_ALIASES = ("Activ to Visa", "Activ to MC", "Activ to")

_VALUE_SKIP = re.compile(
    r"^(?:NEW|ALIPAY|WECHAT|\d{1,2}:\d{2}:\d{2}|set\s+rate|loading|—|-|\.\.\.)$",
    re.I,
)


_VALUE_SEL = "p.chakra-text, span.chakra-text, div.css-1mrfr4g"
_LABEL_SEL = "div.css-vot4m, div.css-1bwri3y"
_TJS_INNER_RE = re.compile(
    r"Activ\s+to\s+(?:MC|Visa)\b[\s\S]{0,80}?([\d][\d\s.,]*)\s*TJS\b",
    re.I,
)
_EUR_XE_INNER_RE = re.compile(
    r"I\s+give\s*\(XE\s+amount\)[\s\S]{0,80}?([\d][\d\s.,]*)\s*EUR\b",
    re.I,
)


async def _read_label_text(label_el: Locator) -> str:
    return (await label_el.inner_text()).strip()


def _label_matches(label_text: str, expected: str, *, partial: bool) -> bool:
    left = label_text.strip().lower()
    right = expected.strip().lower()
    first_line = left.splitlines()[0].strip()
    if not partial:
        return left == right or first_line == right
    if right in left or right in first_line:
        return True
    # «Activ to MC» — да; «I give» для «I give (XE amount)» — нет
    if "(" not in right and (left.startswith(right) or first_line.startswith(right)):
        return True
    return False


def _looks_like_account(raw: str) -> bool:
    return any(ch.isdigit() for ch in raw.replace(" ", ""))


def _row_value_texts(raw: str, label: str, *, partial: bool) -> bool:
    """Подходит ли текст как значение поля (не подпись, не плейсхолдер)."""
    if not raw or _VALUE_SKIP.match(raw):
        return False
    if _label_matches(raw, label, partial=partial):
        return False
    if partial and label.lower() in raw.lower() and not re.search(r"\d", raw):
        return False
    return True


async def read_labeled_field(
    container: Locator | Page,
    label: str,
    *,
    partial: bool = False,
) -> str:
    """
    Значение поля по подписи div.css-vot4m.

    Пример разметки:
        <div class="css-vot4m">Account number</div>
        ...
        <span class="chakra-text">5488 8800 4497 0734</span>
    """
    labels = container.locator(_LABEL_SEL)

    for i in range(await labels.count()):
        label_el = labels.nth(i)
        text = await _read_label_text(label_el)
        if not _label_matches(text, label, partial=partial):
            continue

        row = label_el.locator("xpath=..")
        texts = row.locator(_VALUE_SEL)
        for j in range(await texts.count()):
            raw = (await texts.nth(j).inner_text()).strip()
            if _row_value_texts(raw, label, partial=partial):
                return raw

        for j in range(await row.locator("p.chakra-text, span.chakra-text").count()):
            raw = (
                await row.locator("p.chakra-text, span.chakra-text")
                .nth(j)
                .inner_text()
            ).strip()
            if _row_value_texts(raw, label, partial=partial):
                return raw

    raise PanicError(f"PlatCore: поле {label!r} не найдено или пустое")


async def try_read_labeled_field(
    container: Locator | Page,
    label: str,
    *,
    partial: bool = False,
) -> str | None:
    try:
        return await read_labeled_field(container, label, partial=partial)
    except PanicError:
        return None


async def read_labeled_field_any(
    container: Locator | Page,
    labels: tuple[str, ...],
    *,
    partial: bool = False,
) -> str:
    last_error: PanicError | None = None
    for label in labels:
        try:
            return await read_labeled_field(container, label, partial=partial)
        except PanicError as exc:
            last_error = exc
    raise PanicError(
        f"PlatCore: ни одно поле из {list(labels)!r} не найдено или пустое"
    ) from last_error


async def try_read_labeled_field_any(
    container: Locator | Page,
    labels: tuple[str, ...],
    *,
    partial: bool = False,
) -> str | None:
    try:
        return await read_labeled_field_any(container, labels, partial=partial)
    except PanicError:
        return None


async def read_account_field(container: Locator | Page) -> str:
    for label in ACCOUNT_FIELD_LABELS:
        raw = await try_read_labeled_field(container, label, partial=False)
        if raw and _looks_like_account(raw):
            return raw
    raise PanicError("PlatCore: счёт не найден на карточке сделки")


async def read_holder_field(container: Locator | Page) -> str:
    for label in OWNER_LABELS:
        raw = await try_read_labeled_field(container, label, partial=True)
        if raw:
            return raw
    # Pre-accept drawer: подпись Account = ФИО (без цифр), см. span.chakra-text
    name_raw = await try_read_labeled_field(container, "Account", partial=False)
    if name_raw and not _looks_like_account(name_raw):
        return name_raw
    return ""


async def read_owner_field(container: Locator | Page) -> str:
    return await read_holder_field(container)


async def _hz_calc_roots(container: Locator | Page, page: Page | None = None) -> list[Locator]:
    roots: list[Locator] = []
    for loc in (
        container.locator("#hz-calc[data-sig], [data-hz][data-sig]"),
        *((page.locator("#hz-calc[data-sig]:visible"),) if page is not None else ()),
    ):
        for i in range(await loc.count()):
            el = loc.nth(i)
            try:
                if await el.is_visible():
                    roots.append(el)
            except Exception:
                continue
    return roots


async def _read_labeled_in_hz_calc(
    container: Locator | Page,
    label_re: re.Pattern[str],
    *,
    page: Page | None = None,
) -> str | None:
    raw = await _read_hz_calc_raw_in_hz_calc(container, label_re, page=page)
    if raw and is_parseable_amount(raw):
        return raw
    return None


async def _read_hz_calc_raw_in_hz_calc(
    container: Locator | Page,
    label_re: re.Pattern[str],
    *,
    page: Page | None = None,
) -> str | None:
    """Значение поля hz-calc по подписи — в т.ч. «set rate» до появления суммы."""
    for root in await _hz_calc_roots(container, page):
        labels = root.locator("div.css-vot4m")
        for i in range(await labels.count()):
            label_el = labels.nth(i)
            text = await _read_label_text(label_el)
            if not label_re.search(text):
                continue
            row = label_el.locator("xpath=..")
            for j in range(await row.locator("p.chakra-text, span.chakra-text").count()):
                raw = (
                    await row.locator("p.chakra-text, span.chakra-text")
                    .nth(j)
                    .inner_text()
                ).strip()
                # Не брать текст подписи (вложенный <p>I give</p>) — только сумму
                if (
                    raw
                    and raw != text
                    and re.search(r"\d", raw)
                    and not _label_matches(raw, text, partial=False)
                ):
                    return raw
            blob = re.sub(r"\s+", " ", (await row.inner_text()).strip())
            label_txt = text.splitlines()[0].strip()
            rest = blob
            if rest.lower().startswith(label_txt.lower()):
                rest = rest[len(label_txt) :].strip()
            match = _HZ_ROW_AMOUNT_RE.search(rest)
            if match:
                return f"{match.group(1).strip()} {match.group(2).upper()}"
    return None


_HZ_LABEL_I_GIVE_EXACT = re.compile(r"^I give$", re.I)
_HZ_LABEL_XE_AMOUNT = re.compile(r"I give \(XE amount\)", re.I)
_HZ_LABEL_ACTIV_TO = re.compile(r"Activ\s+to", re.I)
_HZ_ROW_AMOUNT_RE = re.compile(
    r"([\d][\d\s.,]*)\s*(TJS|EUR|USD)\b",
    re.I,
)


async def _hz_calc_has_label(
    container: Locator | Page,
    label_re: re.Pattern[str],
    *,
    page: Page | None = None,
) -> bool:
    for root in await _hz_calc_roots(container, page):
        labels = root.locator("div.css-vot4m")
        for i in range(await labels.count()):
            text = await _read_label_text(labels.nth(i))
            if label_re.search(text):
                return True
    return False


async def _detect_hz_calc_eur_mode(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str:
    """
    Два варианта Approve hz-calc:
    - xe_field: есть строка «I give (XE amount)» → EUR ждём там;
    - usd_only: только «I give» USD + Activ to TJS, без XE → EUR из data-sig.
    """
    if await _hz_calc_has_label(container, _HZ_LABEL_XE_AMOUNT, page=page):
        return "xe_field"
    has_igive = await _hz_calc_has_label(container, _HZ_LABEL_I_GIVE_EXACT, page=page)
    has_activ = await _hz_calc_has_label(container, _HZ_LABEL_ACTIV_TO, page=page)
    if has_igive and has_activ:
        return "usd_only"
    return "unknown"


async def hz_calc_eur_loading_hint(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str:
    """
    Промежуточное состояние hz-calc:
    - xe_field: сначала «I give» USD, потом «I give (XE amount)» EUR;
    - usd_only: XE-строки нет, EUR считаем из data-sig.
    """
    mode = await _detect_hz_calc_eur_mode(container, page=page)
    igive = await _read_hz_calc_raw_in_hz_calc(
        container, _HZ_LABEL_I_GIVE_EXACT, page=page
    )
    activ = await _read_hz_calc_raw_in_hz_calc(
        container, _HZ_LABEL_ACTIV_TO, page=page
    )
    if mode == "usd_only":
        sig_eur = await _try_eur_from_hz_calc_sig(container, page=page)
        parts = [f"I give={igive or '?'}", f"Activ to={activ or '?'}"]
        if sig_eur:
            parts.append(f"EUR≈{sig_eur} (data-sig, только справка)")
        parts.append("→ банк: USD из I give")
        return "; ".join(parts)

    xe = await _read_hz_calc_raw_in_hz_calc(
        container, _HZ_LABEL_XE_AMOUNT, page=page
    )
    parts: list[str] = []
    if igive:
        parts.append(f"I give={igive}")
    if xe:
        if is_parseable_amount(xe):
            _, cur = parse_amount(xe)
            parts.append(f"XE amount={xe}")
            if cur == "EUR":
                return xe
        else:
            parts.append(f"XE amount: {xe!r}")
    elif igive:
        parts.append("XE amount: set rate / загрузка")

    if not parts:
        return ""
    base = "; ".join(parts)
    if igive and (not xe or not is_parseable_amount(xe)):
        _, cur = parse_amount(igive) if is_parseable_amount(igive) else (None, "")
        if cur == "USD" or not xe:
            return f"{base} → ждём I give (XE amount) EUR"
    return base


async def _read_tjs_from_inner_text(container: Locator | Page) -> str | None:
    try:
        text = await container.inner_text()
    except Exception:
        return None
    match = _TJS_INNER_RE.search(text)
    if not match:
        return None
    return f"{match.group(1).strip()} TJS"


async def _read_eur_xe_from_inner_text(container: Locator | Page) -> str | None:
    try:
        text = await container.inner_text()
    except Exception:
        return None
    match = _EUR_XE_INNER_RE.search(text)
    if not match:
        return None
    return f"{match.group(1).strip()} EUR"


async def try_read_tjs_field(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str | None:
    raw = await _read_labeled_in_hz_calc(container, re.compile(r"Activ\s+to", re.I), page=page)
    if raw:
        return raw
    for label in LABEL_TJS_ALIASES:
        raw = await try_read_labeled_field(container, label, partial=True)
        if raw and is_parseable_amount(raw):
            return raw
    raw = await _read_tjs_from_inner_text(container)
    if raw:
        return raw
    if page is not None:
        raw = await _read_labeled_in_hz_calc(page, re.compile(r"Activ\s+to", re.I))
        if raw:
            return raw
        raw = await _read_tjs_from_inner_text(page.locator("body"))
        if raw:
            return raw
    return None


async def read_tjs_field(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str:
    raw = await try_read_tjs_field(container, page=page)
    if raw:
        return raw
    raise PanicError(
        f"PlatCore: поле TJS ({'/'.join(LABEL_TJS_ALIASES)}) не найдено или пустое"
    )


async def wait_for_tjs_on_modal(
    page: Page,
    block: Locator,
    *,
    timeout_ms: int | None = None,
    verbose: bool = True,
) -> str:
    """Ждём Activ to MC/Visa в hz-calc Approve-модалки."""
    timing = _platcore_timing()
    limit_ms = timeout_ms if timeout_ms is not None else timing["post_accept_eur_timeout_ms"]
    deadline = time.monotonic() + limit_ms / 1000
    last_log = 0.0
    last_hint: str | None = None

    while time.monotonic() < deadline:
        raw = await try_read_tjs_field(block, page=page)
        if raw:
            return raw
        try:
            await block.locator("#hz-calc[data-sig], [data-hz][data-sig]").first.wait_for(
                state="visible",
                timeout=500,
            )
        except Exception:
            pass
        last_hint = await _read_tjs_from_inner_text(block)
        now = time.monotonic()
        if verbose and now - last_log >= 3.0:
            print(
                f"[INFO] PlatCore: ждём TJS в hz-calc… "
                f"{last_hint or 'Activ to MC/Visa ещё пусто'}"
            )
            last_log = now
        await page.wait_for_timeout(400)

    raise PanicError(
        f"PlatCore: TJS не появился за {limit_ms / 1000:.0f} с "
        f"(последнее значение: {last_hint!r})"
    )


async def _try_eur_from_hz_calc_sig(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str | None:
    """
    Вариант hz-calc без строки «I give (XE amount)»: EUR = USD из data-sig × fx.
    Используем только если XE-строки в DOM нет (см. _detect_hz_calc_eur_mode).
    """
    roots: list[Locator] = []
    for scope in (container, page):
        if scope is None:
            continue
        calc = scope.locator("#hz-calc[data-sig], [data-hz][data-sig]")
        for i in range(await calc.count()):
            el = calc.nth(i)
            try:
                if await el.is_visible():
                    roots.append(el)
            except Exception:
                continue
    for calc in roots:
        sig_raw = await calc.get_attribute("data-sig")
        if not sig_raw:
            continue
        try:
            sig = json.loads(sig_raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(sig, list) or len(sig) < 3:
            continue
        try:
            usd = float(sig[2])
        except (TypeError, ValueError):
            continue
        usd_eur: float | None = None
        if len(sig) > 9 and sig[9] not in (None, "", 0):
            try:
                usd_eur = float(sig[9])
            except (TypeError, ValueError):
                usd_eur = None
        if usd_eur is None and len(sig) > 7 and isinstance(sig[7], dict):
            fx = sig[7].get("fx.usd_eur")
            if isinstance(fx, dict) and fx.get("value") not in (None, ""):
                try:
                    usd_eur = float(fx["value"])
                except (TypeError, ValueError):
                    usd_eur = None
        if not usd_eur or usd <= 0:
            continue
        return f"{usd * usd_eur:.2f} EUR"
    return None


def _platcore_timing() -> dict:
    from config_loader import load_config

    cfg = load_config().get("platcore") or {}
    return {
        "post_accept_card_timeout_ms": int(
            cfg.get("post_accept_card_timeout_ms", 60_000)
        ),
        "post_accept_eur_timeout_ms": int(
            cfg.get("post_accept_eur_timeout_ms", 120_000)
        ),
        "confirm_modal_close_ms": int(cfg.get("confirm_modal_close_ms", 30_000)),
        "preview_modal_timeout_ms": int(
            cfg.get("preview_modal_timeout_ms", 30_000)
        ),
    }


async def _is_preview_modal_visible(page: Page) -> bool:
    modal = page.locator(
        '[role="dialog"].chakra-modal__content, [role="dialog"].chakra-slide'
    ).filter(
        has=page.get_by_role("button", name="Decline", exact=True)
    )
    if await modal.count() == 0:
        return False
    try:
        return await modal.first.is_visible()
    except Exception:
        return False


_MODAL_SELECTOR = (
    '[role="dialog"].chakra-modal__content, '
    '[role="dialog"].chakra-slide, '
    "section.chakra-modal__content, .chakra-modal__content"
)


async def _is_confirm_accept_modal_visible(page: Page) -> bool:
    """
    Второй Accept — узкая модалка «подтвердить?».
    Не pre-accept (Decline) и не post-accept (Activ to MC / You send).
    """
    modals = page.locator(_MODAL_SELECTOR)
    for i in range(await modals.count()):
        block = modals.nth(i)
        try:
            if not await block.is_visible():
                continue
        except Exception:
            continue
        if await _block_is_pre_accept(block):
            continue
        accept = block.get_by_role("button", name="Accept", exact=True)
        try:
            if await accept.count() == 0 or not await accept.first.is_visible():
                continue
        except Exception:
            continue
        if await try_read_labeled_field(block, LABEL_YOU_SEND):
            continue
        tjs = await try_read_tjs_field(block)
        if tjs:
            continue
        return True
    return False


async def wait_for_confirm_modal_gone(page: Page, *, timeout_ms: int | None = None) -> None:
    """После 2-го Accept — ждём закрытия только confirm-модалки, не post-accept drawer."""
    timing = _platcore_timing()
    limit_ms = timeout_ms if timeout_ms is not None else timing["confirm_modal_close_ms"]
    deadline = time.monotonic() + limit_ms / 1000
    while time.monotonic() < deadline:
        if not await _is_confirm_accept_modal_visible(page):
            return
        await page.wait_for_timeout(250)
    print(
        "[WARN] PlatCore: confirm-модалка ещё видна — "
        "продолжаем ожидание post-accept"
    )


async def _container_has_exact_label(block: Locator, label: str) -> bool:
    label_re = re.compile(rf"^{re.escape(label)}$", re.I)
    labels = block.locator("div.css-vot4m")
    for i in range(await labels.count()):
        text = (await labels.nth(i).inner_text()).strip()
        if label_re.match(text):
            return True
    return False


async def _block_is_pre_accept(block: Locator) -> bool:
    decline = block.get_by_role("button", name="Decline", exact=True)
    try:
        if await decline.count() > 0 and await decline.first.is_visible():
            return True
    except Exception:
        pass
    return False


async def _block_matches_post_accept(block: Locator) -> bool:
    """Approve-модалка после Accept: You send, без Decline."""
    if await _block_is_pre_accept(block):
        return False
    you_send = await try_read_labeled_field(block, LABEL_YOU_SEND)
    return bool(you_send and is_parseable_amount(you_send))


async def _collect_post_accept_container_candidates(page: Page) -> list[Locator]:
    """Сначала модалка после Accept, затем inline chakra-stack."""
    candidates: list[Locator] = []
    modals = page.locator(_MODAL_SELECTOR)
    for i in range(await modals.count()):
        block = modals.nth(i)
        try:
            if not await block.is_visible():
                continue
        except Exception:
            continue
        candidates.append(block)

    stacks = page.locator("div.chakra-stack")
    for i in range(await stacks.count()):
        block = stacks.nth(i)
        try:
            if not await block.is_visible():
                continue
        except Exception:
            continue
        candidates.append(block)
    return candidates


async def _find_post_accept_deal_block(page: Page) -> Locator | None:
    """
    Approve-модалка после Accept: Account number / You send / Money sent.
    Не pre-accept drawer (Decline) и не confirm Accept.
    """
    if await _is_preview_modal_visible(page):
        return None

    for locator in (
        page.locator(_MODAL_SELECTOR).filter(
            has=page.get_by_role("button", name="Money sent", exact=True)
        ),
        page.locator(_MODAL_SELECTOR).filter(
            has=page.locator("div.css-vot4m", has_text=re.compile(r"Account number", re.I))
        ).filter(
            has=page.locator("div.css-vot4m", has_text=re.compile(r"^You send$", re.I))
        ),
        page.locator(_MODAL_SELECTOR).filter(
            has=page.locator("div.css-vot4m", has_text=re.compile(r"^You send$", re.I))
        ),
    ):
        try:
            if await locator.count() > 0 and await locator.first.is_visible():
                if not await _block_is_pre_accept(locator.first):
                    return locator.first
        except Exception:
            continue

    for block in await _collect_post_accept_container_candidates(page):
        if await _block_matches_post_accept(block):
            return block
    return None


# Совместимость со старым именем
_find_post_accept_block = _find_post_accept_deal_block


async def _debug_hz_calc_fields(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str:
    """Все подписи hz-calc на экране — для отладки EUR."""
    parts: list[str] = []
    for root in await _hz_calc_roots(container, page):
        labels = root.locator("div.css-vot4m")
        for i in range(await labels.count()):
            label_el = labels.nth(i)
            label = (await _read_label_text(label_el)).replace("\n", " ")
            row = label_el.locator("xpath=..")
            for j in range(await row.locator("p.chakra-text, span.chakra-text").count()):
                val = (
                    await row.locator("p.chakra-text, span.chakra-text")
                    .nth(j)
                    .inner_text()
                ).strip()
                if val and val != label:
                    parts.append(f"{label}={val}")
    return "; ".join(parts)


async def read_credit_verify_with_source(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> tuple[str | None, str, str]:
    """
    Сумма для сверки в банке («Сумма зачисления»).

    Только из #hz-calc — никогда первый «I give» по всей модалке
    (там часто локальная валюта: 390 THB рядом с 11.55 USD).
    """
    raw = await _read_labeled_in_hz_calc(
        container, _HZ_LABEL_XE_AMOUNT, page=page
    )
    if raw and is_parseable_amount(raw):
        _, cur = parse_amount(raw)
        if cur == "EUR":
            return raw, "EUR", "I give (XE amount)"

    igive = await _read_hz_calc_raw_in_hz_calc(
        container, _HZ_LABEL_I_GIVE_EXACT, page=page
    )
    if igive and is_parseable_amount(igive):
        _, cur = parse_amount(igive)
        if cur == "EUR":
            return igive, "EUR", "I give EUR (hz-calc)"
        if cur == "USD":
            return igive, "USD", "I give USD (hz-calc)"

    # XE иногда только в тексте блока hz-calc
    for root in await _hz_calc_roots(container, page):
        raw = await _read_eur_xe_from_inner_text(root)
        if raw and is_parseable_amount(raw):
            return raw, "EUR", "inner_text XE (hz-calc)"

    return None, "", ""


async def read_eur_with_source(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> tuple[str | None, str]:
    """Только EUR (legacy). Для банка используйте read_credit_verify_with_source."""
    raw, cur, source = await read_credit_verify_with_source(container, page=page)
    if raw and cur == "EUR":
        return raw, source
    return None, ""


async def try_read_eur_field(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str | None:
    raw, _source = await read_eur_with_source(container, page=page)
    return raw


async def dump_hz_calc_fields(
    container: Locator | Page,
    *,
    page: Page | None = None,
) -> str:
    return await _debug_hz_calc_fields(container, page=page)


async def dump_hz_calc_on_screen(page: Page) -> str:
    block = await _find_post_accept_deal_block(page)
    container = block if block is not None else page
    return await _debug_hz_calc_fields(container, page=page)


async def refresh_deal_eur_from_platcore_page(
    page: Page, deal: TzkDeal
) -> tuple[TzkDeal, str]:
    """Перед банком: перечитать EUR/USD для сверки с открытой Approve-модалки."""
    from dataclasses import replace

    await page.bring_to_front()
    await page.wait_for_timeout(500)

    hz_dump = await dump_hz_calc_on_screen(page)
    if hz_dump:
        print(f"[PlatCore] hz-calc на вкладке: {hz_dump}")

    block = await _find_post_accept_deal_block(page)
    container = block if block is not None else page

    credit_raw, credit_cur, source = await read_credit_verify_with_source(
        container, page=page
    )
    if not credit_raw:
        credit_raw = await wait_for_credit_on_card(page, container, verbose=True)
        _, credit_cur, source = await read_credit_verify_with_source(
            container, page=page
        )
        if not source:
            source = "wait credit"

    amount, cur = parse_amount(credit_raw)
    if cur == "EUR":
        updated = replace(deal, amount_eur=amount, amount_usd=0.0)
        label = "EUR"
    elif cur == "USD":
        updated = replace(deal, amount_eur=0.0, amount_usd=amount)
        label = "USD"
    else:
        raise PanicError(
            f"PlatCore: сверка с вкладки — не EUR/USD ({credit_raw!r}, {source!r})"
        )

    prev = deal.amount_usd if cur == "USD" else deal.amount_eur
    if abs(prev - amount) > 0.02:
        print(
            f"[WARN] {label} обновлён с вкладки PlatCore: "
            f"{prev:g} → {amount:g} ({source})"
        )
    else:
        print(f"[PlatCore] {label} с вкладки: {amount:g} ({source}) ✓")

    return updated, source


async def wait_for_credit_on_card(
    page: Page,
    block: Locator,
    *,
    timeout_ms: int | None = None,
    verbose: bool = True,
) -> str:
    """Ждём сумму для сверки в банке: XE EUR или I give USD."""
    timing = _platcore_timing()
    limit_ms = timeout_ms if timeout_ms is not None else timing["post_accept_eur_timeout_ms"]
    mode = "unknown"
    wait_xe = True
    deadline = time.monotonic() + limit_ms / 1000
    last_log = 0.0
    last_hint: str | None = None

    while time.monotonic() < deadline:
        mode = await _detect_hz_calc_eur_mode(block, page=page)
        wait_xe = mode == "xe_field"

        raw, _cur, source = await read_credit_verify_with_source(
            block, page=page
        )
        if raw:
            if verbose and "USD" in (source or ""):
                print(f"[PlatCore] USD для банка: {raw}")
            return raw

        last_hint = await hz_calc_eur_loading_hint(block, page=page)
        if not last_hint:
            for root in await _hz_calc_roots(block, page):
                last_hint = await _read_eur_xe_from_inner_text(root)
                if last_hint:
                    break

        now = time.monotonic()
        if verbose and now - last_log >= 3.0:
            if wait_xe:
                print(
                    f"[INFO] PlatCore: ждём I give (XE amount) EUR… "
                    f"{last_hint or 'hz-calc пусто / set rate'}"
                )
            else:
                print(
                    f"[INFO] PlatCore: ждём I give USD/EUR в hz-calc… "
                    f"{last_hint or 'hz-calc пусто'}"
                )
            last_log = now
        await page.wait_for_timeout(400)

    raise PanicError(
        f"PlatCore: сумма для банка не появилась за {limit_ms / 1000:.0f} с "
        f"(последнее значение: {last_hint!r})"
    )


async def wait_for_eur_on_card(
    page: Page,
    block: Locator,
    *,
    timeout_ms: int | None = None,
    verbose: bool = True,
) -> str:
    return await wait_for_credit_on_card(
        page, block, timeout_ms=timeout_ms, verbose=verbose
    )


async def wait_for_post_accept_deal_card(
    page: Page,
    *,
    timeout_ms: int | None = None,
    verbose: bool = True,
) -> Locator:
    """Этап 2: модалка Approve после Accept — ждём появления You send."""
    timing = _platcore_timing()
    limit_ms = (
        timeout_ms if timeout_ms is not None else timing["post_accept_card_timeout_ms"]
    )
    await page.wait_for_timeout(350)

    deadline = time.monotonic() + limit_ms / 1000
    while time.monotonic() < deadline:
        block = await _find_post_accept_deal_block(page)
        if block is not None:
            if verbose:
                you_send = await try_read_labeled_field(block, LABEL_YOU_SEND)
                tjs = await try_read_tjs_field(block, page=page)
                credit_raw, credit_cur, credit_src = await read_credit_verify_with_source(
                    block, page=page
                )
                if credit_raw:
                    credit_disp = f"{credit_raw} ({credit_src})"
                else:
                    hz_hint = await hz_calc_eur_loading_hint(block, page=page)
                    credit_disp = hz_hint or "hz-calc…"
                print(
                    f"[PlatCore] Approve-модалка: You send {you_send}, "
                    f"TJS {tjs or '?'}, банк {credit_disp}"
                )
            return block
        await page.wait_for_timeout(200)

    raise PanicError(
        "PlatCore: Approve-модалка после Accept не найдена "
        f"(ожидали {LABEL_YOU_SEND!r} в открытом dialog)"
    )


# Старое имя
wait_for_deal_card = wait_for_post_accept_deal_card


async def _read_post_accept_fields(
    block: Locator,
    page: Page,
) -> tuple[str, str, str]:
    """Счёт, имя, You send с Approve-модалки (TJS/EUR — отдельно, с ожиданием hz-calc)."""
    account_raw = await read_account_field(block)
    holder_raw = await read_holder_field(block)
    you_send_raw = await read_labeled_field(block, LABEL_YOU_SEND, partial=False)
    return account_raw, holder_raw, you_send_raw


async def read_deal_from_card(page: Page, val_cfg: dict) -> TzkDeal:
    """Текущие данные с post-accept карточки (без сверки со списком)."""
    block = await _find_post_accept_deal_block(page)
    if block is None:
        raise PanicError("PlatCore: post-accept карточка не найдена")

    account_raw, holder_raw, you_send_raw = await _read_post_accept_fields(block, page)
    tjs_raw = await wait_for_tjs_on_modal(page, block, verbose=False)
    credit_raw, cur_credit, _ = await read_credit_verify_with_source(block, page=page)
    if not credit_raw:
        credit_raw = await wait_for_credit_on_card(page, block, verbose=False)
    amount_credit, cur_credit = parse_amount(credit_raw)

    min_digits = val_cfg["account_min_digits"]
    max_digits = val_cfg["account_max_digits"]
    account_digits = clean_account(account_raw, min_digits=min_digits, max_digits=max_digits)
    holder = optional_clean_holder_name(holder_raw)
    amount_check, check_cur = parse_amount(you_send_raw)
    amount_tjs, _cur_tjs = parse_amount(tjs_raw)
    amount_eur = amount_credit if cur_credit == "EUR" else 0.0
    amount_usd = amount_credit if cur_credit == "USD" else 0.0

    return TzkDeal(
        task_id="",
        account_raw=account_raw,
        account_digits=account_digits,
        holder_name=holder,
        amount_check=amount_check,
        amount_check_currency=check_cur,
        amount_tjs=amount_tjs,
        amount_eur=amount_eur,
        amount_usd=amount_usd,
        payment_method="",
    )


def preview_to_deal(
    preview,
    val_cfg: dict,
) -> TzkDeal:
    """Dry-run: данные из строки списка (как CNY preview_to_deal)."""
    min_digits = val_cfg["account_min_digits"]
    max_digits = val_cfg["account_max_digits"]
    amount, currency = parse_amount(preview.amount_raw)
    card = clean_account(
        preview.account_raw, min_digits=min_digits, max_digits=max_digits
    )
    holder = optional_clean_holder_name(preview.holder_raw)
    return TzkDeal(
        task_id=preview_to_task_id(preview),
        account_raw=preview.account_raw,
        account_digits=card,
        holder_name=holder,
        amount_check=amount,
        amount_check_currency=currency,
        amount_tjs=0.0,
        amount_eur=0.0,
        payment_method=preview.payment_method,
    )


async def extract_and_verify_deal_from_card(
    page: Page,
    preview,
    val_cfg: dict,
    *,
    block: Locator | None = None,
    pre_tjs: str | None = None,
    pre_eur: str | None = None,
) -> TzkDeal:
    """
    Этап 2: с post-accept модалки — единственный источник правды для bank flow.
    Сверка с preview из списка; расхождение → PanicError.
    """
    from platcore_list import read_platcore_order_id

    if block is None:
        block = await _find_post_accept_deal_block(page)
    if block is None:
        raise PanicError("PlatCore: post-accept модалка не найдена перед чтением")

    account_raw, holder_raw, you_send_raw = await _read_post_accept_fields(block, page)

    tjs_raw = await try_read_tjs_field(block, page=page) or pre_tjs
    if not tjs_raw:
        tjs_raw = await wait_for_tjs_on_modal(page, block)

    credit_raw, credit_cur, credit_source = await read_credit_verify_with_source(
        block, page=page
    )
    if not credit_raw and pre_eur:
        credit_raw, credit_cur, credit_source = pre_eur, "EUR", "pre-accept snapshot"
    if not credit_raw:
        credit_raw = await wait_for_credit_on_card(page, block)
        _, credit_cur, credit_source = await read_credit_verify_with_source(
            block, page=page
        )
        if not credit_source:
            credit_source = "wait credit"

    min_digits = val_cfg["account_min_digits"]
    max_digits = val_cfg["account_max_digits"]

    account_digits = clean_account(account_raw, min_digits=min_digits, max_digits=max_digits)
    list_account = clean_account(
        preview.account_raw, min_digits=min_digits, max_digits=max_digits
    )
    holder = optional_clean_holder_name(holder_raw)
    list_holder = optional_clean_holder_name(preview.holder_raw)

    if account_digits != list_account:
        raise PanicError(
            f"Anti mix-up PlatCore: счёт на карточке {account_digits!r} "
            f"≠ списка {list_account!r}"
        )
    if not amounts_match(preview.amount_raw, you_send_raw):
        raise PanicError(
            f"Anti mix-up PlatCore: You send {parse_amount_value(you_send_raw):g} "
            f"≠ списка {parse_amount_value(preview.amount_raw):g}"
        )
    if list_holder and holder and holder != list_holder:
        raise PanicError(
            f"Anti mix-up PlatCore: имя {holder!r} ≠ списка {list_holder!r}"
        )

    amount_check, check_cur = parse_amount(you_send_raw)
    amount_tjs, cur_tjs = parse_amount(tjs_raw)
    amount_credit, cur_credit = parse_amount(credit_raw)

    if cur_tjs != "TJS":
        raise PanicError(f"Ожидали TJS в Activ to Visa/MC, получено: {tjs_raw!r}")
    if cur_credit not in ("EUR", "USD"):
        raise PanicError(
            f"Ожидали EUR или USD для банка, получено: {credit_raw!r}"
        )

    amount_eur = amount_credit if cur_credit == "EUR" else 0.0
    amount_usd = amount_credit if cur_credit == "USD" else 0.0
    credit_label = f"{amount_credit:g} {cur_credit}"

    order_id = await read_platcore_order_id(page)
    print(
        f"[PlatCore] Карточка = список ✓ | orderId={order_id or '?'} | "
        f"You send {amount_check:g} {check_cur} | "
        f"{amount_tjs:g} TJS | банк {credit_label} ({credit_source}) | счёт {account_digits}"
        + (f" | {holder}" if holder else "")
    )

    return TzkDeal(
        task_id=preview_to_task_id(preview),
        account_raw=account_raw,
        account_digits=account_digits,
        holder_name=holder,
        amount_check=amount_check,
        amount_check_currency=check_cur,
        amount_tjs=amount_tjs,
        amount_eur=amount_eur,
        amount_usd=amount_usd,
        payment_method=preview.payment_method,
    )


async def read_deal_from_page(
    page: Page,
    preview,
    val_cfg: dict,
    *,
    block: Locator | None = None,
) -> TzkDeal:
    """Обратная совместимость → extract_and_verify_deal_from_card."""
    _ = block
    return await extract_and_verify_deal_from_card(page, preview, val_cfg)


async def verify_open_card_matches_preview(
    page: Page,
    preview,
    val_cfg: dict,
    *,
    label: str = "перед Accept",
    modal: Locator | None = None,
) -> None:
    """
    Этап 1: после клика по строке, до Accept — модалка = выбранная строка.
    Сверка счёта / I give / имя со списком; при расхождении — PANIC без Accept.
    """
    from platcore_list import wait_for_order_preview_modal

    if modal is None:
        modal = await wait_for_order_preview_modal(page)

    account_raw = await read_account_field(modal)
    holder_raw = await read_holder_field(modal)
    i_give_raw = await read_labeled_field(modal, LABEL_I_GIVE, partial=False)

    min_digits = val_cfg["account_min_digits"]
    max_digits = val_cfg["account_max_digits"]

    card_account = clean_account(account_raw, min_digits=min_digits, max_digits=max_digits)
    list_account = clean_account(
        preview.account_raw, min_digits=min_digits, max_digits=max_digits
    )
    card_holder = optional_clean_holder_name(holder_raw)
    list_holder = optional_clean_holder_name(preview.holder_raw)

    if card_account != list_account:
        raise PanicError(
            f"{label}: счёт в списке {list_account!r}, "
            f"в модалке {card_account!r} — Accept не нажимаем"
        )
    if not amounts_match(preview.amount_raw, i_give_raw):
        list_val = parse_amount_value(preview.amount_raw)
        card_val = parse_amount_value(i_give_raw)
        raise PanicError(
            f"{label}: сумма в списке {list_val:g}, "
            f"в модалке I give {card_val:g} — Accept не нажимаем"
        )
    if list_holder and card_holder and card_holder != list_holder:
        raise PanicError(
            f"{label}: имя в списке {list_holder!r}, "
            f"в модалке {card_holder!r} — Accept не нажимаем"
        )

    _, list_cur = parse_amount(preview.amount_raw)
    _, give_cur = parse_amount(i_give_raw)
    print(
        f"[PlatCore] {label} ✓ | модалка = список | "
        f"I give {parse_amount_value(i_give_raw):g} {give_cur or list_cur or '?'} | "
        f"счёт {card_account}"
        + (f" | {card_holder}" if card_holder else "")
    )


async def verify_pre_accept_matches_preview(
    page: Page,
    preview,
    val_cfg: dict,
    *,
    label: str = "перед Accept",
) -> None:
    await verify_open_card_matches_preview(page, preview, val_cfg, label=label)


async def verify_card_matches_preview(
    page: Page,
    preview,
    val_cfg: dict,
    *,
    label: str = "перед Accept",
) -> None:
    await verify_pre_accept_matches_preview(page, preview, val_cfg, label=label)
