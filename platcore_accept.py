"""Accept сделки на PlatCore (tzk)."""

from __future__ import annotations

from playwright.async_api import Page

from human import HumanTiming, human_click
from models import TzkDeal
from platcore_card import (
    extract_and_verify_deal_from_card,
    preview_to_deal,
    read_credit_verify_with_source,
    try_read_tjs_field,
    dump_hz_calc_fields,
    verify_open_card_matches_preview,
    wait_for_post_accept_deal_card,
)
from platcore_list import (
    dismiss_pointer_blockers,
    is_duplicate_deal_toast,
    resolve_row_by_preview,
    wait_for_confirm_accept,
    wait_for_deal_accept_button,
    wait_for_order_preview_modal,
)
from validators import PanicError


async def _raise_if_accept_blocked(page: Page, *, fallback: str) -> None:
    toast = await dismiss_pointer_blockers(page)
    if is_duplicate_deal_toast(toast):
        raise PanicError(
            f"PlatCore: сделка/реквизиты уже заняты — {toast[:240]}"
        )
    if toast:
        raise PanicError(f"PlatCore Accept: {toast[:240]}")
    raise PanicError(fallback)


async def accept_deal_on_page(
    page: Page,
    *,
    timing: HumanTiming,
    fake: bool,
) -> None:
    accept_btn = await wait_for_deal_accept_button(
        page,
        timeout_ms=timing.accept_wait_timeout_ms,
        debug=timing.debug_timing,
    )
    if fake:
        print("[DRY-RUN] Accept найден, но НЕ нажат")
        return

    try:
        await human_click(accept_btn, timing=timing)
    except PanicError:
        raise
    except Exception as exc:
        await _raise_if_accept_blocked(
            page,
            fallback=f"Не удалось нажать Accept: {exc}",
        )

    try:
        confirm_btn = await wait_for_confirm_accept(
            page,
            timeout_ms=timing.confirm_accept_timeout_ms,
            debug=timing.debug_timing,
        )
        await human_click(confirm_btn, timing=timing)
        print("[PlatCore] Подтверждение: второй Accept в модальном окне")
    except PanicError:
        raise
    except Exception as exc:
        await _raise_if_accept_blocked(
            page,
            fallback=(
                f"Модальное окно подтверждения Accept не появилось / "
                f"не кликнулось за {timing.confirm_accept_timeout_ms} мс: {exc}"
            ),
        )


async def accept_deal_in_same_tab(
    page: Page,
    _row_locator,
    preview,
    *,
    timing: HumanTiming,
    fake_accept: bool,
    val_cfg: dict,
) -> tuple[TzkDeal, Page]:
    row_loc = await resolve_row_by_preview(page, preview, val_cfg)
    if row_loc is None:
        raise PanicError(
            f"Строка списка не найдена перед Accept: "
            f"{preview.time_text} | {preview.amount_raw} | "
            f"{preview.account_raw} | {preview.holder_raw}"
        )

    # Этап 1: тап по строке → сверяем, что открылась та же сделка (anti mix-up).
    try:
        await human_click(row_loc, timing=timing)
    except PanicError:
        raise
    except Exception as exc:
        await _raise_if_accept_blocked(
            page,
            fallback=f"Не удалось открыть строку сделки: {exc}",
        )
    await page.wait_for_load_state("domcontentloaded")
    modal = await wait_for_order_preview_modal(page)

    pre_tjs: str | None = None
    pre_eur: str | None = None
    if not fake_accept:
        await verify_open_card_matches_preview(
            page, preview, val_cfg, label="этап 1", modal=modal
        )
        pre_tjs = await try_read_tjs_field(modal, page=page)
        pre_credit, pre_cur, pre_credit_source = await read_credit_verify_with_source(
            modal, page=page
        )
        pre_eur = pre_credit if pre_cur == "EUR" else None
        hz_dump = await dump_hz_calc_fields(modal, page=page)
        if pre_tjs or pre_credit or hz_dump:
            print(
                f"[PlatCore] hz-calc в drawer: TJS {pre_tjs or '?'}, "
                f"банк {pre_credit or '?'} ({pre_credit_source or '—'})"
            )
            if hz_dump:
                print(f"[PlatCore] поля hz-calc: {hz_dump}")

    # Этап 2: Accept → Approve-модалка → читаем всё → bank.
    await accept_deal_on_page(page, timing=timing, fake=fake_accept)

    post_modal = None
    if not fake_accept:
        try:
            post_modal = await wait_for_post_accept_deal_card(page)
        except PanicError as exc:
            await _raise_if_accept_blocked(page, fallback=str(exc))
            raise

    if fake_accept:
        deal = preview_to_deal(preview, val_cfg)
        return deal, page

    deal = await extract_and_verify_deal_from_card(
        page,
        preview,
        val_cfg,
        block=post_modal,
        pre_tjs=pre_tjs,
        pre_eur=pre_eur,
    )
    print(f"[ЭТАП 2] PlatCore: данные с модалки → bank | {deal.task_id}")
    return deal, page
