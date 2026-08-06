"""Список pay-out, скролл Virtuoso, кнопки Accept."""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Locator, Page

from core.models import RowPreview
from core.validators import (
    PanicError,
    clean_account,
    optional_clean_holder_name,
    parse_amount,
    skip_reason_for_card_brand,
    skip_reason_for_preview,
)

LIST_BODY = 'tbody[data-test-id="virtuoso-item-list"]'
ROW_SELECTOR = f"{LIST_BODY} tr"

# Тосты Chakra (не модалки dialog) часто перекрывают кнопки.
_PORTAL_TOAST = (
    ".chakra-portal .chakra-toast, "
    ".chakra-portal [id*='toast'], "
    ".chakra-portal .chakra-alert, "
    ".chakra-portal [role='alert'], "
    ".chakra-portal [data-status], "
    ".chakra-portal .chakra-toast__inner"
)
_PORTAL_CLOSE = (
    ".chakra-portal [aria-label='Close'], "
    ".chakra-portal button[aria-label='Close'], "
    ".chakra-toast [aria-label='Close']"
)
_DUPLICATE_DEAL_RE = re.compile(
    r"already\s+(exists|paid|processed|taken)|"
    r"duplicate|"
    r"уже\s+(есть|оплач|обработ|принят)|"
    r"сделка\s+уже|"
    r"реквизит\w*\s+уже|"
    r"оплачивал",
    re.I,
)

_FIND_SCROLLER_JS = """
() => {
    const scroller = document.querySelector('[data-virtuoso-scroller]');
    if (scroller) return scroller;
    const list = document.querySelector('tbody[data-test-id="virtuoso-item-list"]');
    if (!list) return null;
    let el = list.parentElement;
    while (el) {
        const style = window.getComputedStyle(el);
        const oy = style.overflowY;
        if (
            (oy === 'auto' || oy === 'scroll' || oy === 'overlay')
            && el.scrollHeight > el.clientHeight + 5
        ) {
            return el;
        }
        el = el.parentElement;
    }
    return null;
}
"""

_ROW_STEP_PX_JS = """
(rows) => {
    const row = document.querySelector('tbody[data-test-id="virtuoso-item-list"] tr');
    const h = row ? row.getBoundingClientRect().height : 56;
    return Math.max(40, Math.round(h * rows));
}
"""

_SCROLL_SETTLE_MS = 650


def make_fingerprint(
    time_text: str, amount_raw: str, account_raw: str, holder_raw: str
) -> str:
    amount_key = normalize_list_amount_raw(amount_raw)
    return f"{time_text}|{amount_key}|{account_raw}|{holder_raw}"


def stable_preview_key(preview: RowPreview) -> str:
    amount_key = normalize_list_amount_raw(preview.amount_raw)
    return f"{amount_key}|{preview.account_raw}|{preview.holder_raw}"


def normalize_list_amount_raw(raw: str) -> str:
    """Стабильная строка суммы для fingerprint (любая валюта)."""
    text = raw.replace("\u00a0", " ").strip()
    amount_re = re.compile(r"-?\s*[\d\s,]+(?:\.\d+)?\s*[A-Za-z]{3}")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if amount_re.search(line):
            return line
    if text:
        return text.splitlines()[0].strip()
    return text


def extract_deal_id_from_url(url: str) -> str:
    match = re.search(r"dealId=([^&]+)", url, re.I)
    return match.group(1) if match else ""


async def wait_for_list(page: Page, timeout_ms: int = 60_000) -> None:
    await page.wait_for_selector(LIST_BODY, timeout=timeout_ms)


async def wait_for_order_preview_modal(
    page: Page,
    *,
    timeout_ms: int | None = None,
) -> Locator:
    if timeout_ms is None:
        try:
            from core.config import load_config

            plat = load_config().get("platcore") or {}
            timeout_ms = int(plat.get("preview_modal_timeout_ms", 30_000))
        except Exception:
            timeout_ms = 30_000
    modal = page.locator(
        '[role="dialog"].chakra-modal__content, [role="dialog"].chakra-slide'
    ).filter(
        has=page.get_by_role("button", name="Decline", exact=True)
    )
    target = modal.first
    await target.wait_for(state="visible", timeout=timeout_ms)
    await target.locator(
        "div.css-vot4m",
        has_text=re.compile(
            r"External client ID|^I give$|Activ to MC",
            re.I,
        ),
    ).first.wait_for(state="visible", timeout=timeout_ms)
    return target


async def read_platcore_order_id(page: Page) -> str:
    url_id = extract_deal_id_from_url(page.url)
    if url_id:
        return url_id

    from platcore.card import try_read_labeled_field

    order_id = await try_read_labeled_field(page, "Order ID")
    if order_id:
        return order_id

    id_line = page.get_by_text(re.compile(r"ID:\s*\S+", re.I))
    if await id_line.count():
        text = (await id_line.first.inner_text()).strip()
        match = re.search(r"ID:\s*(\S+)", text, re.I)
        if match:
            return match.group(1)
    return ""


def _accept_in_order_info_panel(page: Page) -> Locator:
    order_block = page.get_by_label(re.compile(r"Order info", re.I))
    return order_block.get_by_role("button", name="Accept", exact=True)


def _accept_in_action_stack(page: Page, *, require: str) -> Locator:
    stack = page.locator("div.chakra-stack").filter(
        has=page.get_by_role("button", name="Accept", exact=True)
    )
    if require == "redirect":
        stack = stack.filter(
            has=page.get_by_role("button", name="Redirect", exact=True)
        )
    else:
        stack = stack.filter(
            has=page.get_by_role("button", name="Decline", exact=True)
        )
    return stack.first.get_by_role("button", name="Accept", exact=True)


async def wait_for_deal_accept_button(
    page: Page, *, timeout_ms: int, debug: bool = False
) -> Locator:
    deadline = time.monotonic() + timeout_ms / 1000
    strategies: list[tuple[str, Locator]] = [
        ("Order info → Accept", _accept_in_order_info_panel(page)),
        (
            "панель Accept + Redirect",
            _accept_in_action_stack(page, require="redirect"),
        ),
        (
            "панель Accept + Decline",
            _accept_in_action_stack(page, require="decline"),
        ),
    ]

    last_error: Exception | None = None
    for name, locator in strategies:
        remaining_ms = int(max(0.1, deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        try:
            target = locator.first
            await target.wait_for(state="visible", timeout=remaining_ms)
            if debug:
                print(f"[TIMING] Accept найден: {name}")
            return target
        except Exception as exc:
            last_error = exc

    raise TimeoutError(
        f"Accept в карточке сделки не появился за {timeout_ms} мс"
    ) from last_error


async def wait_for_confirm_accept(
    page: Page, *, timeout_ms: int, debug: bool = False
) -> Locator:
    modal = page.locator(
        '[role="dialog"], section.chakra-modal__content, .chakra-modal__content'
    )
    btn = modal.get_by_role("button", name="Accept", exact=True).first
    try:
        await btn.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        btn = page.get_by_role("button", name="Accept", exact=True).last
        await btn.wait_for(state="visible", timeout=timeout_ms)
    if debug:
        print("[TIMING] Модальное подтверждение Accept найдено")
    return btn


async def _platcore_list_scroller(page: Page):
    handle = await page.evaluate_handle(_FIND_SCROLLER_JS)
    if not handle:
        return None
    is_null = await handle.evaluate("el => el == null")
    if is_null:
        await handle.dispose()
        return None
    return handle


async def scroll_platcore_list_to_top(page: Page) -> None:
    handle = await _platcore_list_scroller(page)
    if not handle:
        return
    await handle.evaluate("el => { if (el) el.scrollTop = 0; }")
    await handle.dispose()
    await page.wait_for_timeout(_SCROLL_SETTLE_MS)


async def step_platcore_list_scroll(page: Page, *, rows: int = 2) -> bool:
    handle = await _platcore_list_scroller(page)
    if not handle:
        return False
    at_bottom = await handle.evaluate(
        "el => el && el.scrollTop + el.clientHeight >= el.scrollHeight - 2"
    )
    if at_bottom:
        await handle.evaluate("el => { if (el) el.scrollTop = 0; }")
        await handle.dispose()
        await page.wait_for_timeout(_SCROLL_SETTLE_MS)
        return False

    step_px = await page.evaluate(_ROW_STEP_PX_JS, rows)
    await handle.evaluate(
        "(el, step) => { if (el) el.scrollTop += step; }",
        step_px,
    )
    await handle.dispose()
    await page.wait_for_timeout(_SCROLL_SETTLE_MS)
    return True


async def nudge_platcore_list_scroll(page: Page) -> bool:
    """Прокрутить список вниз на ~2 строки.

    Returns:
        True — ещё есть куда скроллить вниз.
        False — дошли до конца списка и вернулись наверх (полный круг).
    """
    return await step_platcore_list_scroll(page, rows=2)


async def _parse_amount_cell(amount_td: Locator) -> tuple[str, str]:
    """Фиат + USDT из ячейки суммы. Не завязан только на хэш-классы Chakra."""
    fiat_loc = amount_td.locator("div.css-rs9kze")
    usdt_loc = amount_td.locator("div.css-1p66ug3")
    amount_raw = ""
    amount_usdt_raw = ""
    if await fiat_loc.count() > 0:
        amount_raw = normalize_list_amount_raw(
            (await fiat_loc.first.inner_text()).strip()
        )
    if await usdt_loc.count() > 0:
        amount_usdt_raw = normalize_list_amount_raw(
            (await usdt_loc.first.inner_text()).strip()
        )

    if amount_raw and amount_usdt_raw:
        return amount_raw, amount_usdt_raw

    cell_text = (await amount_td.inner_text()).strip()
    usdt_re = re.compile(r"-?\s*[\d\s,]+(?:\.\d+)?\s*USDT\b", re.I)
    other_re = re.compile(r"-?\s*[\d\s,]+(?:\.\d+)?\s*[A-Za-z]{3}\b")
    for line in cell_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not amount_usdt_raw and usdt_re.search(line):
            amount_usdt_raw = normalize_list_amount_raw(line)
            continue
        if not amount_raw and other_re.search(line) and not usdt_re.search(line):
            amount_raw = normalize_list_amount_raw(line)

    if not amount_raw:
        divs = amount_td.locator("div")
        if await divs.count() > 0:
            amount_raw = normalize_list_amount_raw(
                (await divs.first.inner_text()).strip()
            )
        elif cell_text:
            amount_raw = normalize_list_amount_raw(cell_text)

    return amount_raw, amount_usdt_raw


async def _parse_row_preview(row: Locator) -> RowPreview:
    tds = row.locator("td")
    if await tds.count() < 7:
        raise PanicError("Неожиданная структура строки таблицы (< 7 колонок)")

    payment_method = (await tds.nth(0).inner_text()).strip()
    time_text = (await tds.nth(1).inner_text()).strip()

    amount_raw, amount_usdt_raw = await _parse_amount_cell(tds.nth(2))

    requisites_cell = tds.nth(5)
    account_loc = requisites_cell.locator("div.css-rs9kze")
    holder_loc = requisites_cell.locator("div.css-1p66ug3")

    if await account_loc.count() > 0:
        account_raw = (await account_loc.first.inner_text()).strip()
        holder_raw = ""
        if await holder_loc.count() > 0:
            holder_raw = (await holder_loc.first.inner_text()).strip()
    else:
        parts = requisites_cell.locator("div.css-j7qwjs > div")
        if await parts.count() < 1:
            parts = requisites_cell.locator("span.chakra-text, p.chakra-text")
        if await parts.count() < 1:
            raise PanicError("Не найдены реквизиты в строке (счёт)")
        account_raw = (await parts.nth(0).inner_text()).strip()
        holder_raw = ""
        if await parts.count() >= 2:
            holder_raw = (await parts.nth(1).inner_text()).strip()

    fp = make_fingerprint(time_text, amount_raw, account_raw, holder_raw)
    return RowPreview(
        fingerprint=fp,
        time_text=time_text,
        amount_raw=amount_raw,
        account_raw=account_raw,
        holder_raw=holder_raw,
        payment_method=payment_method,
        amount_usdt_raw=amount_usdt_raw,
    )


async def collect_new_row_previews(
    page: Page,
    *,
    allowed_statuses: frozenset[str] | None = None,
) -> list[tuple[Locator, RowPreview]]:
    await wait_for_list(page)
    rows = page.locator(ROW_SELECTOR)
    result: list[tuple[Locator, RowPreview]] = []
    allowed = (
        allowed_statuses
        if allowed_statuses is not None
        else list_statuses_from_url(page.url)
    )

    for i in range(await rows.count()):
        row = rows.nth(i)
        if await row.locator("td").count() < 7:
            continue
        badge = row.locator("td").nth(6).locator("span.chakra-badge")
        if await badge.count() == 0:
            continue
        status = (await badge.first.inner_text()).strip().lower()
        if status not in allowed:
            continue
        try:
            preview = await _parse_row_preview(row)
        except PanicError:
            continue
        result.append((row, preview))

    return result


def list_statuses_from_url(url: str) -> frozenset[str]:
    """
    Какие статусы строк брать из списка.
    Берём ?status= из monitor_url (new / pending / all).
    По умолчанию — только new.
    """
    raw = ""
    try:
        q = parse_qs(urlparse(url or "").query)
        values = q.get("status") or []
        raw = (values[0] if values else "").strip().lower()
    except Exception:
        raw = ""
    if not raw:
        return frozenset({"new"})
    if raw in ("all", "*", "any"):
        return frozenset({"new", "pending"})
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(parts) if parts else frozenset({"new"})


async def collect_eligible_new_previews_scrolled(
    page: Page,
    *,
    min_amount: float | None,
    max_amount: float | None,
    min_count: int,
    poll_sec: float = 2.0,
    allow_visa: bool = True,
    allow_mastercard: bool = True,
) -> list[RowPreview]:
    await wait_for_list(page)
    await scroll_platcore_list_to_top(page)

    seen_stable: set[str] = set()
    eligible: list[RowPreview] = []

    while len(eligible) < min_count:
        for _, preview in await collect_new_row_previews(page):
            stable = stable_preview_key(preview)
            if stable in seen_stable:
                continue
            skip = skip_reason_for_preview(
                preview.amount_usdt_raw,
                min_amount=min_amount,
                max_amount=max_amount,
            )
            if skip:
                continue
            skip_card = skip_reason_for_card_brand(
                preview.account_raw,
                allow_visa=allow_visa,
                allow_mastercard=allow_mastercard,
            )
            if skip_card:
                continue
            seen_stable.add(stable)
            eligible.append(preview)
            if len(eligible) >= min_count:
                break

        if len(eligible) >= min_count:
            break

        moved = await step_platcore_list_scroll(page, rows=2)
        if not moved:
            await page.wait_for_timeout(int(poll_sec * 1000))

    await scroll_platcore_list_to_top(page)
    return eligible


async def resolve_row_by_preview(
    page: Page,
    preview: RowPreview,
    val_cfg: dict,
    *,
    allowed_statuses: frozenset[str] | None = None,
) -> Locator | None:
    min_digits = val_cfg["account_min_digits"]
    max_digits = val_cfg["account_max_digits"]
    try:
        want_card = clean_account(
            preview.account_raw, min_digits=min_digits, max_digits=max_digits
        )
        want_amount, _ = parse_amount(preview.amount_raw)
        want_holder = optional_clean_holder_name(preview.holder_raw)
    except PanicError:
        return None

    for row_loc, current in await collect_new_row_previews(
        page, allowed_statuses=allowed_statuses
    ):
        if current.time_text != preview.time_text:
            continue
        try:
            card = clean_account(
                current.account_raw, min_digits=min_digits, max_digits=max_digits
            )
            amount, _ = parse_amount(current.amount_raw)
            holder = optional_clean_holder_name(current.holder_raw)
        except PanicError:
            continue
        if card != want_card or abs(amount - want_amount) > 0.01:
            continue
        if want_holder and holder and holder != want_holder:
            continue
        return row_loc
    return None


async def read_platcore_toast_text(page: Page) -> str:
    """Текст видимых тостов/алертов в chakra-portal (ошибка Accept и т.п.)."""
    chunks: list[str] = []
    loc = page.locator(_PORTAL_TOAST)
    try:
        n = min(await loc.count(), 8)
    except Exception:
        return ""
    for i in range(n):
        item = loc.nth(i)
        try:
            if not await item.is_visible():
                continue
            text = (await item.inner_text()).strip()
        except Exception:
            continue
        if text and text not in chunks:
            chunks.append(text)
    return "\n".join(chunks).strip()


def is_duplicate_deal_toast(text: str) -> bool:
    return bool(text and _DUPLICATE_DEAL_RE.search(text))


async def dismiss_chakra_toasts(page: Page) -> bool:
    """Закрыть тосты Chakra, которые перехватывают pointer events."""
    closed = False
    closes = page.locator(_PORTAL_CLOSE)
    try:
        n = min(await closes.count(), 6)
    except Exception:
        n = 0
    for i in range(n):
        btn = closes.nth(i)
        try:
            if await btn.is_visible():
                await btn.click(timeout=1_500, force=True)
                closed = True
        except Exception:
            continue
    if closed:
        await page.wait_for_timeout(200)
        return True
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        return True
    except Exception:
        return False


async def dismiss_pointer_blockers(page: Page) -> str:
    """
    Убрать оверлеи перед кликом.
    Возвращает текст тоста, если он похож на ошибку дубля/уже оплачено.
    """
    toast = await read_platcore_toast_text(page)
    await dismiss_chakra_toasts(page)
    if is_duplicate_deal_toast(toast):
        return toast
    # После закрытия текст мог пропасть — вернём то, что успели прочитать.
    return toast if toast else ""


async def dismiss_order_preview_modal(page: Page) -> None:
    await dismiss_chakra_toasts(page)
    modal = page.locator('[role="dialog"].chakra-modal__content').filter(
        has=page.get_by_role("button", name="Decline", exact=True)
    )
    if await modal.count() == 0:
        return
    try:
        if not await modal.first.is_visible():
            return
    except Exception:
        return

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


async def dismiss_any_platcore_modal(page: Page, *, presses: int = 3) -> None:
    """Закрыть любую видимую Chakra-модалку (Order info / сделка / Dispute)."""
    dialog = page.locator(
        '[role="dialog"].chakra-modal__content, '
        '[role="dialog"].chakra-slide, '
        '[role="dialog"]'
    )
    for _ in range(presses):
        visible = False
        try:
            n = min(await dialog.count(), 6)
            for i in range(n):
                if await dialog.nth(i).is_visible():
                    visible = True
                    break
        except Exception:
            visible = False
        if not visible:
            return
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(350)
        except Exception:
            return


async def return_platcore_list_from_preview(page: Page, monitor_url: str) -> None:
    """Вернуться к списку pay-out. Модалка поверх списка ≠ уже на списке."""
    await dismiss_chakra_toasts(page)
    await dismiss_order_preview_modal(page)
    await dismiss_any_platcore_modal(page)

    url = (page.url or "").lower()
    on_list_url = "pay-out" in url
    try:
        q = parse_qs(urlparse(page.url or "").query)
        has_deal = bool((q.get("dealId") or q.get("dealid") or [""])[0])
    except Exception:
        has_deal = "dealid=" in url

    dialog_open = False
    dialog = page.locator(
        '[role="dialog"].chakra-modal__content, [role="dialog"]'
    )
    try:
        for i in range(min(await dialog.count(), 6)):
            if await dialog.nth(i).is_visible():
                dialog_open = True
                break
    except Exception:
        dialog_open = True

    if on_list_url and not has_deal and not dialog_open:
        try:
            await page.wait_for_selector(LIST_BODY, timeout=3_000)
            return
        except Exception:
            pass

    await page.goto(monitor_url, wait_until="domcontentloaded")
    await wait_for_list(page)
    await dismiss_chakra_toasts(page)
    await dismiss_any_platcore_modal(page)


def is_phase1_pick_recoverable(exc: PanicError) -> bool:
    msg = str(exc)
    return (
        "перед Accept" in msg
        or "Строка списка не найдена перед Accept" in msg
    )
