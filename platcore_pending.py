"""Pending-сделки: клик строки → Approve → банк → чеки.

Как new-флоу, но вместо Accept — Approve (сделки уже кинули в pending).
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import BrowserContext, Page

from deal_bridge import save_pending_deal
from gui_progress import PipelineProgressTracker
from human import HumanTiming, human_click, parse_human_timing
from job_control import JobStopped, raise_if_stopped
from logkit import debug, info, ok, section, warn
from models import TzkDeal
from platcore_card import (
    extract_and_verify_deal_from_card,
    preview_to_deal,
    wait_for_post_accept_deal_card,
)
from platcore_completion import click_order_info_approve
from platcore_list import (
    collect_new_row_previews,
    dismiss_chakra_toasts,
    nudge_platcore_list_scroll,
    read_platcore_order_id,
    resolve_row_by_preview,
    return_platcore_list_from_preview,
)
from platcore_pipeline import (
    AcceptedDeal,
    ensure_platcore_list_tab,
    format_deal_brief,
    run_bank_for_deal,
    _validation_amount_limits,
    _validation_card_brands,
)
from recovery import deal_summary_from_accepted, offer_recovery_choice
from validators import (
    PanicError,
    deal_to_dict,
    parse_amount_value,
    session_requisites_key,
    skip_reason_for_card_brand,
    skip_reason_for_preview,
    skip_reason_for_session_duplicate,
)

_PENDING_STATUSES = frozenset({"pending"})


class DisputePendingSkip(Exception):
    """В модалке кнопка Dispute (уже диспут) — не Approve / не банк."""


async def page_shows_active_dispute(page: Page) -> bool:
    """
    Уже в диспуте: кнопка «Dispute».
    Ещё нет: «Open dispute».
    """
    # exact=True — не путать с «Open dispute»
    btn = page.get_by_role("button", name="Dispute", exact=True)
    try:
        n = await btn.count()
    except Exception:
        n = 0
    for i in range(n):
        try:
            if await btn.nth(i).is_visible():
                return True
        except Exception:
            continue

    # Fallback по тексту кнопки (без «Open …»)
    try:
        count = await page.locator("button").count()
    except Exception:
        count = 0
    for i in range(min(count, 40)):
        try:
            b = page.locator("button").nth(i)
            if not await b.is_visible():
                continue
            text = " ".join(((await b.inner_text()) or "").split())
            if text.casefold() == "dispute":
                return True
        except Exception:
            continue
    return False


def pending_monitor_url(monitor_url: str) -> str:
    """Тот же pay-out, но status=pending."""
    raw = (monitor_url or "").strip()
    if not raw:
        return "https://hz.temkitemki.work/pay-out?status=pending&limit=100"
    parts = urlparse(raw)
    q = parse_qs(parts.query, keep_blank_values=True)
    q["status"] = ["pending"]
    if "limit" not in q:
        q["limit"] = ["100"]
    query = urlencode({k: v[-1] if isinstance(v, list) else v for k, v in q.items()})
    return urlunparse(parts._replace(query=query))


async def claim_one_pending(
    list_page: Page,
    row_locator,
    preview,
    *,
    cfg: dict,
    timing: HumanTiming,
    deal_index: int,
    requisites_in_run: dict[str, int],
) -> AcceptedDeal:
    """Строка pending → Approve → модалка с реквизитами (далее банк как у new)."""
    val_cfg = cfg["validation"]
    row_loc = await resolve_row_by_preview(
        list_page,
        preview,
        val_cfg,
        allowed_statuses=_PENDING_STATUSES,
    )
    if row_loc is None:
        row_loc = row_locator
    if row_loc is None:
        raise PanicError(f"Строка pending не найдена: {preview.fingerprint}")

    try:
        await human_click(row_loc, timing=timing)
    except Exception as exc:
        raise PanicError(f"Не удалось открыть pending-строку: {exc}") from exc

    await list_page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(0.45)

    # Уже диспут (кнопка Dispute, не Open dispute) → skip
    if await page_shows_active_dispute(list_page):
        raise DisputePendingSkip(
            f"уже Dispute: {preview.fingerprint}"
        )

    await click_order_info_approve(list_page, timing=timing)

    # После Approve модалка могла обновиться — на всякий
    if await page_shows_active_dispute(list_page):
        raise DisputePendingSkip(
            f"после Approve всё ещё Dispute: {preview.fingerprint}"
        )

    order_id = await read_platcore_order_id(list_page)
    try:
        modal = await wait_for_post_accept_deal_card(list_page, verbose=False)
        deal = await extract_and_verify_deal_from_card(
            list_page, preview, val_cfg, block=modal
        )
    except PanicError:
        info("Не прочитали модалку — беру реквизиты из строки списка")
        deal = preview_to_deal(preview, val_cfg)

    deal = TzkDeal(
        task_id=deal.task_id,
        account_raw=deal.account_raw,
        account_digits=deal.account_digits,
        holder_name=deal.holder_name,
        amount_check=deal.amount_check,
        amount_check_currency=deal.amount_check_currency,
        amount_tjs=deal.amount_tjs,
        amount_eur=deal.amount_eur,
        amount_usd=deal.amount_usd,
        payment_method=deal.payment_method,
        order_id=order_id or deal.order_id,
    )

    key = session_requisites_key(deal.account_digits, deal.holder_name)
    if key in requisites_in_run:
        prev = requisites_in_run[key]
        raise PanicError(
            f"Реквизиты+ФИО уже в сделке #{prev} — "
            f"pending #{deal_index} пропуск (дубль)"
        )
    requisites_in_run[key] = deal_index

    data = deal_to_dict(deal)
    save_pending_deal(deal, order_id=deal.order_id)
    amount_usdt = 0.0
    if preview.amount_usdt_raw:
        try:
            amount_usdt = parse_amount_value(preview.amount_usdt_raw)
        except PanicError:
            amount_usdt = 0.0

    accepted = AcceptedDeal(
        index=deal_index,
        deal=deal,
        order_id=deal.order_id,
        fingerprint=preview.fingerprint,
        data=data,
        platcore_page=list_page,
        amount_usdt=amount_usdt,
        bank_skipped=False,
    )
    ok(f"Pending→Approve: {format_deal_brief(accepted)}")
    return accepted


async def claim_pending_deals_loop(
    context: BrowserContext,
    cfg: dict,
) -> tuple[list[AcceptedDeal], dict[str, Page]]:
    """Пачка pending: Approve → банк (как new) → вкладки для фазы чеков."""
    dash_cfg = cfg["dashboard"]
    pipe_cfg = cfg.get("pipeline") or {}
    val_cfg = cfg["validation"]
    timing = parse_human_timing(cfg)

    max_deals = int(pipe_cfg.get("max_deals_per_run", 5))
    max_empty_passes = int(pipe_cfg.get("max_empty_list_passes", 2))
    spawn_delay = float(pipe_cfg.get("spawn_deal_delay_sec", 2.0))
    confirm_next = bool(pipe_cfg.get("confirm_next_deal", False))
    min_amount, max_amount = _validation_amount_limits(val_cfg)
    allow_visa, allow_mc = _validation_card_brands(val_cfg)
    monitor_url = pending_monitor_url(str(dash_cfg.get("monitor_url") or ""))

    seen: set[str] = set()
    seen_seeded = False
    # Карта+ФИО уже открывали и там Dispute — клонов в списке не тыкаем
    dispute_requisites: set[str] = set()
    accepted_deals: list[AcceptedDeal] = []
    spawned = 0
    empty_list_passes = 0
    list_page: Page | None = None
    requisites_in_run: dict[str, int] = {}

    section(
        f"Pending→Approve→банк: до {max_deals} "
        f"(стоп после {max_empty_passes} пустых кругов)"
    )
    progress = PipelineProgressTracker(total=max_deals)
    progress.begin_search()
    info(f"Список: {monitor_url}")
    if min_amount is not None or max_amount is not None:
        parts = []
        if min_amount is not None:
            parts.append(f">= {min_amount:g}")
        if max_amount is not None:
            parts.append(f"<= {max_amount:g}")
        info(f"USDT (вход): {' и '.join(parts)}")
    brands = []
    if allow_visa:
        brands.append("Visa(4…)")
    if allow_mc:
        brands.append("MC(5…)")
    info(f"Карты: {', '.join(brands) if brands else 'нет (всё skip)'}")

    while spawned < max_deals:
        raise_if_stopped()
        if list_page is None or list_page.is_closed():
            list_page = await ensure_platcore_list_tab(
                context,
                monitor_url,
                reuse_existing=(spawned == 0),
            )
            if spawned > 0:
                debug("Новая вкладка со списком pending")

            if (
                not seen_seeded
                and not dash_cfg.get("process_existing_on_start", True)
            ):
                rows_seed = await collect_new_row_previews(
                    list_page, allowed_statuses=_PENDING_STATUSES
                )
                for _, p in rows_seed:
                    seen.add(p.fingerprint)
                seen_seeded = True
                if rows_seed:
                    debug(f"При старте пропущено {len(rows_seed)} висящих pending")

        assert list_page is not None
        rows = await collect_new_row_previews(
            list_page, allowed_statuses=_PENDING_STATUSES
        )
        picked = False

        for row_loc, preview in rows:
            if preview.fingerprint in seen:
                continue
            skip = skip_reason_for_preview(
                preview.amount_usdt_raw,
                min_amount=min_amount,
                max_amount=max_amount,
            )
            if skip:
                info(
                    f"Пропуск (фильтр USDT): {preview.amount_usdt_raw or '—'} | "
                    f"{preview.amount_raw} — {skip}"
                )
                seen.add(preview.fingerprint)
                continue

            skip_card = skip_reason_for_card_brand(
                preview.account_raw,
                allow_visa=allow_visa,
                allow_mastercard=allow_mc,
            )
            if skip_card:
                info(
                    f"Пропуск (фильтр карты): {preview.account_raw or '—'} — {skip_card}"
                )
                seen.add(preview.fingerprint)
                continue

            skip_dup = skip_reason_for_session_duplicate(
                preview.account_raw,
                preview.holder_raw,
                requisites_in_run=requisites_in_run,
            )
            if skip_dup:
                info(
                    f"Пропуск (дубль в сессии): {preview.account_raw or '—'} | "
                    f"{preview.holder_raw or '—'} — {skip_dup}"
                )
                seen.add(preview.fingerprint)
                continue

            req_key = session_requisites_key(
                preview.account_raw, preview.holder_raw
            )
            if req_key and req_key in dispute_requisites:
                debug(
                    f"Пропуск (карта уже Dispute в этом прогоне): "
                    f"{preview.account_raw or '—'} | {preview.holder_raw or '—'}"
                )
                seen.add(preview.fingerprint)
                continue

            debug(f"Pending: {preview.fingerprint}")
            seen.add(preview.fingerprint)
            next_index = spawned + 1

            try:
                accepted = await claim_one_pending(
                    list_page,
                    row_loc,
                    preview,
                    cfg=cfg,
                    timing=timing,
                    deal_index=next_index,
                    requisites_in_run=requisites_in_run,
                )
            except DisputePendingSkip as skip_exc:
                info(f"Пропуск (уже Dispute): {skip_exc}")
                if req_key:
                    dispute_requisites.add(req_key)
                # Не picked / не empty reset — иначе вечный круг по диспутам
                if list_page and not list_page.is_closed():
                    try:
                        await return_platcore_list_from_preview(
                            list_page, monitor_url
                        )
                        debug("Вернулся к списку pending")
                    except Exception as ret_exc:
                        info(f"Не вернулся к списку: {ret_exc}")
                        try:
                            await list_page.goto(
                                monitor_url, wait_until="domcontentloaded"
                            )
                        except Exception:
                            list_page = None
                break
            except JobStopped:
                raise
            except Exception as exc:
                panic = (
                    exc
                    if isinstance(exc, PanicError)
                    else PanicError(f"Pending Approve: {exc}")
                )
                progress.start_accept(next_index, preview)
                try:
                    await offer_recovery_choice(
                        panic,
                        stage="Pending Approve",
                        deal_index=next_index,
                    )
                except JobStopped:
                    raise
                spawned += 1
                empty_list_passes = 0
                picked = True
                progress.mark_skipped(next_index, "Не удалось Approve")
                warn(
                    f"Pending #{next_index} пропущен — слот {spawned}/{max_deals}"
                )
                if list_page and not list_page.is_closed():
                    try:
                        await dismiss_chakra_toasts(list_page)
                        await return_platcore_list_from_preview(
                            list_page, monitor_url
                        )
                    except Exception:
                        list_page = None
                break

            progress.start_accept(next_index, preview)
            accepted_deals.append(accepted)
            spawned += 1
            empty_list_passes = 0
            list_page = None
            picked = True
            progress.mark_accepted(accepted)

            bank_ok = False
            while True:
                try:
                    progress.mark_paying(accepted.index)
                    await run_bank_for_deal(
                        accepted.deal,
                        cfg,
                        platcore_page=accepted.platcore_page,
                    )
                    bank_ok = True
                    progress.mark_paid(accepted.index)
                    try:
                        from cancel_notify_watch import register_paid_deal

                        d = accepted.data or {}
                        digits = str(
                            (d.get("account") or {}).get("digits")
                            or accepted.deal.account_digits
                            or ""
                        )
                        inp = d.get("amount_input") or {}
                        amt = float(
                            inp.get("value")
                            if inp.get("value") is not None
                            else accepted.deal.amount_tjs
                            or 0
                        )
                        register_paid_deal(
                            index=accepted.index,
                            holder=str(
                                d.get("holder_name")
                                or accepted.deal.holder_name
                                or ""
                            ),
                            card_digits=digits,
                            amount_tjs=amt,
                            order_id=accepted.order_id or "",
                        )
                    except Exception as reg_exc:
                        info(f"Учёт выплаты для отмен: {reg_exc}")
                    break
                except JobStopped:
                    raise
                except Exception as exc:
                    from recovery import is_post_payment_error

                    post_paid = is_post_payment_error(exc)
                    choice = await offer_recovery_choice(
                        exc,
                        stage="банк",
                        deal_index=accepted.index,
                        summary=deal_summary_from_accepted(accepted),
                        allow_retry=not post_paid,
                    )
                    if choice == "retry":
                        continue
                    if post_paid:
                        warn(
                            f"Сделка #{accepted.index}: оплата была, "
                            "«На главную» не нажалась — считаем оплаченной"
                        )
                        bank_ok = True
                        progress.mark_paid(accepted.index)
                        try:
                            from cancel_notify_watch import register_paid_deal

                            d = accepted.data or {}
                            digits = str(
                                (d.get("account") or {}).get("digits")
                                or accepted.deal.account_digits
                                or ""
                            )
                            inp = d.get("amount_input") or {}
                            amt = float(
                                inp.get("value")
                                if inp.get("value") is not None
                                else accepted.deal.amount_tjs
                                or 0
                            )
                            register_paid_deal(
                                index=accepted.index,
                                holder=str(
                                    d.get("holder_name")
                                    or accepted.deal.holder_name
                                    or ""
                                ),
                                card_digits=digits,
                                amount_tjs=amt,
                                order_id=accepted.order_id or "",
                            )
                        except Exception as reg_exc:
                            info(f"Учёт выплаты для отмен: {reg_exc}")
                        break
                    warn(
                        f"Сделка #{accepted.index} пропущена — "
                        f"перевод не выполнен ({exc})"
                    )
                    accepted.bank_skipped = True
                    progress.mark_skipped(
                        accepted.index, "Перевод не выполнен"
                    )
                    break

            if not bank_ok:
                debug(f"#{accepted.index}: банк skip — в фазе чеков будет Отмена")

            if spawned < max_deals and spawn_delay > 0:
                await asyncio.sleep(spawn_delay)
            if spawned < max_deals and confirm_next:
                from user_prompts import wait_user_confirm

                await wait_user_confirm(
                    f"Следующая pending-сделка "
                    f"({spawned}/{max_deals} готово)?"
                )
            break

        if picked:
            continue

        still_scrolling = False
        if list_page and not list_page.is_closed():
            still_scrolling = await nudge_platcore_list_scroll(list_page)
        if still_scrolling:
            continue

        empty_list_passes += 1
        info(
            f"Список pending без новой сделки (круг {empty_list_passes}/"
            f"{max_empty_passes}), оплачено {len(accepted_deals)}/{max_deals}"
        )
        if empty_list_passes >= max_empty_passes:
            if accepted_deals:
                warn(
                    f"Новых pending нет после {max_empty_passes} кругов — "
                    f"завершаю ({len(accepted_deals)}/{max_deals}) и иду к чекам"
                )
            else:
                warn(
                    f"Подходящих pending нет после {max_empty_passes} кругов — "
                    f"стоп (0/{max_deals})"
                )
            break
        await asyncio.sleep(float(dash_cfg.get("poll_interval_sec", 2.0)))

    ok(f"Pending→Approve→банк завершён: {len(accepted_deals)}/{max_deals}")
    page_by_order: dict[str, Page] = {}
    for accepted in accepted_deals:
        page = accepted.platcore_page
        if page is not None and not page.is_closed() and accepted.order_id:
            page_by_order[accepted.order_id] = page
    return accepted_deals, page_by_order
