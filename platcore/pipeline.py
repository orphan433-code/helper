"""PlatCore: парсинг списка, скролл Virtuoso, Accept — tzk."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page

from core.human import HumanTiming, parse_human_timing
from core.logkit import debug, error, info, is_verbose, ok, section, warn
from core.models import TzkDeal
from platcore.accept import accept_deal_in_same_tab
from platcore.list import (
    collect_eligible_new_previews_scrolled,
    collect_new_row_previews,
    dismiss_chakra_toasts,
    is_phase1_pick_recoverable,
    nudge_platcore_list_scroll,
    read_platcore_order_id,
    return_platcore_list_from_preview,
    wait_for_list,
)
from core.browser_session import close_stale_tabs
from core.deal_bridge import deal_to_transfer_form, save_pending_deal
from ui.progress import PipelineProgressTracker
from ui.job_control import JobStopped, raise_if_stopped
from core.recovery import deal_summary_from_accepted, offer_recovery_choice
from core.deals_ui_local import pipeline_ui_bin_prefixes
from core.validators import (
    PanicError,
    deal_to_dict,
    parse_amount_value,
    session_requisites_key,
    skip_reason_for_card_bin,
    skip_reason_for_card_brand,
    skip_reason_for_preview,
    skip_reason_for_session_duplicate,
)

@dataclass
class AcceptedDeal:
    index: int
    deal: TzkDeal
    order_id: str
    fingerprint: str
    data: dict
    platcore_page: Page | None = None
    amount_usdt: float = 0.0
    bank_skipped: bool = False
    ledger: dict | None = None


def format_deal_brief(accepted: AcceptedDeal) -> str:
    d = accepted.data
    last4 = d["account"]["digits"][-4:] if d["account"]["digits"] else "????"
    holder = d["holder_name"] or "—"
    inp = d["amount_input"]
    ver = d["amount_verify"]
    return (
        f"#{accepted.index} *{last4} | "
        f"{inp['value']:g} {inp['currency']} → {ver['value']:g} {ver['currency']} | "
        f"{holder}"
    )


def format_deal_console(accepted: AcceptedDeal) -> str:
    """Полный дамп — только при logging.verbose."""
    d = accepted.data
    lines = [
        f"[{accepted.index}] Принята сделка",
        f"  order_id      : {d['order_id']}",
        f"  account       : {d['account']['digits']} (raw: {d['account']['raw']})",
        f"  holder        : {d['holder_name'] or '—'}",
        f"  amount_check  : {d['amount_check']['value']:g} {d['amount_check']['currency'] or '?'}",
        f"  amount_input  : {d['amount_input']['value']:g} {d['amount_input']['currency']}",
        f"  amount_verify : {d['amount_verify']['value']:g} {d['amount_verify']['currency']}"
        + (f" ({d['amount_eur_source']})" if d.get("amount_eur_source") else ""),
        f"  method        : {d['payment_method']}",
        f"  fingerprint   : {accepted.fingerprint}",
    ]
    return "\n".join(lines)


async def ensure_platcore_list_tab(
    context: BrowserContext,
    monitor_url: str,
    *,
    reuse_existing: bool = False,
) -> Page:
    if reuse_existing and context.pages:
        page = context.pages[0]
        if not page.is_closed():
            await page.goto(monitor_url, wait_until="domcontentloaded")
            await wait_for_list(page)
            debug("PlatCore: список в открытой вкладке")
            return page

    page = await context.new_page()
    await page.goto(monitor_url, wait_until="domcontentloaded")
    await wait_for_list(page)
    return page


def _validation_amount_limits(val_cfg: dict) -> tuple[float | None, float | None]:
    lo = val_cfg.get("min_amount")
    if lo is None:
        lo = val_cfg.get("min_amount_tjs")
    hi = val_cfg.get("max_amount")
    if hi is None:
        hi = val_cfg.get("max_amount_tjs")
    return lo, hi


def _validation_card_brands(val_cfg: dict) -> tuple[bool, bool]:
    # Временно дефолт: только Visa (4…), MC (5…) выкл.
    allow_visa = bool(val_cfg.get("allow_visa", True))
    allow_mc = bool(val_cfg.get("allow_mastercard", False))
    return allow_visa, allow_mc


async def wait_for_min_eligible_deals(
    context: BrowserContext,
    cfg: dict,
    *,
    min_count: int,
) -> Page:
    dash_cfg = cfg["dashboard"]
    val_cfg = cfg["validation"]
    poll_sec = float(dash_cfg.get("poll_interval_sec", 2.0))
    min_amount, max_amount = _validation_amount_limits(val_cfg)
    allow_visa, allow_mc = _validation_card_brands(val_cfg)
    monitor_url = dash_cfg["monitor_url"]

    list_page = await ensure_platcore_list_tab(
        context, monitor_url, reuse_existing=True
    )
    section(f"Ожидание {min_count} подходящих сделок")
    eligible = await collect_eligible_new_previews_scrolled(
        list_page,
        min_amount=min_amount,
        max_amount=max_amount,
        allow_visa=allow_visa,
        allow_mastercard=allow_mc,
        min_count=min_count,
        poll_sec=poll_sec,
    )
    ok(f"Найдено {len(eligible)} подходящих — старт Accept")
    for i, preview in enumerate(eligible[:min_count], start=1):
        debug(f"  [{i}] {preview.fingerprint}")
    return list_page


async def accept_one_deal(
    list_page: Page,
    row_locator,
    preview,
    *,
    cfg: dict,
    timing: HumanTiming,
    fake_accept: bool,
    deal_index: int,
    requisites_in_run: dict[str, int],
) -> AcceptedDeal:
    deal, platcore_page = await accept_deal_in_same_tab(
        list_page,
        row_locator,
        preview,
        timing=timing,
        fake_accept=fake_accept,
        val_cfg=cfg["validation"],
    )
    order_id = await read_platcore_order_id(platcore_page)
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
        order_id=order_id,
    )

    key = session_requisites_key(deal.account_digits, deal.holder_name)
    if key in requisites_in_run:
        prev = requisites_in_run[key]
        raise PanicError(
            f"Реквизиты+ФИО уже в сделке #{prev} — "
            f"сделка #{deal_index} (PlatCore не примет дубль в pending)"
        )
    requisites_in_run[key] = deal_index

    data = deal_to_dict(deal)
    save_pending_deal(deal, order_id=order_id)
    amount_usdt = 0.0
    if preview.amount_usdt_raw:
        try:
            amount_usdt = parse_amount_value(preview.amount_usdt_raw)
        except PanicError:
            amount_usdt = 0.0
    accepted = AcceptedDeal(
        index=deal_index,
        deal=deal,
        order_id=order_id,
        fingerprint=preview.fingerprint,
        data=data,
        platcore_page=platcore_page,
        amount_usdt=amount_usdt,
    )
    ok(f"Accept: {format_deal_brief(accepted)}")
    if is_verbose():
        debug(format_deal_console(accepted))
    return accepted


def _deal_has_credit_amount(deal: TzkDeal) -> bool:
    return deal.amount_eur > 0 or deal.amount_usd > 0


async def run_bank_for_deal(
    deal: TzkDeal,
    cfg: dict,
    *,
    platcore_page: Page | None = None,
) -> None:
    """После Accept: PIN → навигация → форма с данными сделки."""
    pipe_cfg = cfg.get("pipeline") or {}
    if not pipe_cfg.get("run_bank_after_accept"):
        return
    if (cfg.get("stage1") or {}).get("fake_accept"):
        debug("fake_accept — bank пропущен")
        return

    from bank.flow import run_bank_flow
    from core.config import bank_settings
    from platcore.card import refresh_deal_eur_from_platcore_page

    handoff_t0 = time.monotonic()
    bank_cfg = bank_settings(cfg)
    skip_refresh = bool(bank_cfg.get("skip_eur_refresh_if_present", True))
    need_refresh = (
        platcore_page is not None
        and not platcore_page.is_closed()
        and (not skip_refresh or not _deal_has_credit_amount(deal))
    )

    if need_refresh:
        debug("Перечитываем EUR с вкладки PlatCore")
        deal, eur_source = await refresh_deal_eur_from_platcore_page(
            platcore_page, deal
        )
        save_pending_deal(
            deal, order_id=deal.order_id, amount_eur_source=eur_source
        )
    elif skip_refresh and _deal_has_credit_amount(deal):
        label = "EUR" if deal.amount_eur > 0 else "USD"
        amount = deal.amount_eur if deal.amount_eur > 0 else deal.amount_usd
        debug(
            f"EUR/USD уже с Accept ({amount:g} {label}) — "
            f"пропуск refresh перед банком"
        )

    transfer = deal_to_transfer_form(deal)

    pre_handoff_ms = (time.monotonic() - handoff_t0) * 1000
    info(
        f"Банк: {transfer.account[-4:]} | {transfer.amount_tjs:g} TJS "
        f"(подготовка {pre_handoff_ms:.0f} ms → handoff)"
    )

    bank_t0 = time.monotonic()
    await asyncio.to_thread(
        run_bank_flow,
        transfer=transfer,
        run_pin=True,
        run_nav=True,
        run_form=True,
        verbose=False,
        handoff_started_at=handoff_t0,
    )
    bank_ms = (time.monotonic() - bank_t0) * 1000
    ok(f"Банк: перевод выполнен ({bank_ms:.0f} ms)")


def _register_paid_from_accepted(accepted: AcceptedDeal) -> None:
    try:
        from notify.cancel import register_paid_deal

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
            holder=str(d.get("holder_name") or accepted.deal.holder_name or ""),
            card_digits=digits,
            amount_tjs=amt,
            order_id=accepted.order_id or "",
        )
    except Exception as reg_exc:
        info(f"Учёт выплаты для отмен: {reg_exc}")


async def pay_accepted_deal(
    accepted: AcceptedDeal,
    cfg: dict,
    *,
    progress: PipelineProgressTracker | None = None,
) -> bool:
    """PIN / форма / перевод. True если оплата ушла."""
    while True:
        try:
            if progress is not None:
                progress.mark_paying(accepted.index)
            await run_bank_for_deal(
                accepted.deal,
                cfg,
                platcore_page=accepted.platcore_page,
            )
            if progress is not None:
                progress.mark_paid(accepted.index)
            _register_paid_from_accepted(accepted)
            return True
        except JobStopped:
            raise
        except Exception as exc:
            from core.recovery import is_post_payment_error

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
                if progress is not None:
                    progress.mark_paid(accepted.index)
                _register_paid_from_accepted(accepted)
                return True
            warn(
                f"Сделка #{accepted.index} пропущена — "
                f"банк не выполнен, слот засчитан "
                f"(остаётся в пуле чеков для отмены)"
            )
            accepted.bank_skipped = True
            if progress is not None:
                progress.mark_skipped(accepted.index, "Перевод не выполнен")
            return False


async def accept_deals_loop(
    context: BrowserContext, cfg: dict
) -> tuple[list[AcceptedDeal], dict[str, Page]]:
    dash_cfg = cfg["dashboard"]
    pipe_cfg = cfg.get("pipeline") or {}
    stage1 = cfg.get("stage1") or {}
    val_cfg = cfg["validation"]

    max_deals = int(pipe_cfg.get("max_deals_per_run", 5))
    # Сколько полных проходов списка без новой сделки — потом стоп (не ждать max вечно).
    # 2 = один круг + второй круг без новинок → завершить Accept и идти дальше по флоу.
    max_empty_passes = int(pipe_cfg.get("max_empty_list_passes", 2))
    if max_empty_passes < 1:
        max_empty_passes = 1
    confirm_next = bool(pipe_cfg.get("confirm_next_deal", False))
    spawn_delay = float(pipe_cfg.get("spawn_deal_delay_sec", 2.0))
    fake_accept = bool(stage1.get("fake_accept", False))
    min_amount, max_amount = _validation_amount_limits(val_cfg)
    allow_visa, allow_mc = _validation_card_brands(val_cfg)
    bin_prefixes = pipeline_ui_bin_prefixes()
    monitor_url = dash_cfg["monitor_url"]
    timing = parse_human_timing(cfg)

    min_before = int(pipe_cfg.get("min_deals_before_start", 0))
    initial_list: Page | None = None
    skip_seed = False
    if min_before > 0:
        initial_list = await wait_for_min_eligible_deals(
            context, cfg, min_count=min_before
        )
        skip_seed = True

    seen: set[str] = set()
    seen_seeded = False
    accepted_deals: list[AcceptedDeal] = []
    spawned = 0
    empty_list_passes = 0
    list_page: Page | None = initial_list
    requisites_in_run: dict[str, int] = {}

    section(f"Accept: до {max_deals} сделок (стоп после {max_empty_passes} пустых кругов списка)")
    progress = PipelineProgressTracker(total=max_deals)
    progress.begin_search()
    if min_amount is not None or max_amount is not None:
        parts = []
        if min_amount is not None:
            parts.append(f">= {min_amount:g}")
        if max_amount is not None:
            parts.append(f"<= {max_amount:g}")
        info(f"USDT (вход): {' и '.join(parts)}")
    if bin_prefixes:
        info(f"BIN: только {', '.join(p + '*' for p in bin_prefixes)} (Visa/MC не смотрим)")
    else:
        brands = []
        if allow_visa:
            brands.append("Visa(4…)")
        if allow_mc:
            brands.append("MC(5…)")
        info(f"Карты: {', '.join(brands) if brands else 'нет (всё skip)'}")
    info("Статусы списка: new")
    if fake_accept:
        warn("Accept в dry-run (fake_accept)")
    debug(
        f"Между сделками: "
        f"{'Enter' if confirm_next else f'авто {spawn_delay:g} с'}"
    )

    while spawned < max_deals:
        raise_if_stopped()
        if list_page is None or list_page.is_closed():
            list_page = await ensure_platcore_list_tab(
                context,
                monitor_url,
                reuse_existing=(spawned == 0 and initial_list is None),
            )
            if spawned > 0:
                debug("Новая вкладка со списком")

            if (
                not seen_seeded
                and not skip_seed
                and not dash_cfg.get("process_existing_on_start", False)
            ):
                rows_seed = await collect_new_row_previews(
                    list_page, allowed_statuses=frozenset({"new"})
                )
                for _, p in rows_seed:
                    seen.add(p.fingerprint)
                seen_seeded = True
                if rows_seed:
                    debug(f"При старте пропущено {len(rows_seed)} висящих new")

        rows = await collect_new_row_previews(
            list_page, allowed_statuses=frozenset({"new"})
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
                # info: иначе при verbose=false кажется, что «сделка подходит», а скролл идёт
                info(
                    f"Пропуск (фильтр USDT): {preview.amount_usdt_raw or '—'} | "
                    f"{preview.amount_raw} — {skip}"
                )
                seen.add(preview.fingerprint)
                continue

            if bin_prefixes:
                skip_bin = skip_reason_for_card_bin(preview.account_raw, bin_prefixes)
                if skip_bin:
                    info(
                        f"Пропуск (фильтр BIN): {preview.account_raw or '—'} — {skip_bin}"
                    )
                    seen.add(preview.fingerprint)
                    continue
            else:
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

            info(f"Accept: {preview.fingerprint}")
            seen.add(preview.fingerprint)
            next_index = spawned + 1
            progress.start_accept(next_index, preview)

            try:
                accepted = await accept_one_deal(
                    list_page,
                    row_loc,
                    preview,
                    cfg=cfg,
                    timing=timing,
                    fake_accept=fake_accept,
                    deal_index=next_index,
                    requisites_in_run=requisites_in_run,
                )
            except JobStopped:
                raise
            except Exception as exc:
                panic = (
                    exc
                    if isinstance(exc, PanicError)
                    else PanicError(f"PlatCore Accept: {exc}")
                )
                if isinstance(panic, PanicError) and is_phase1_pick_recoverable(
                    panic
                ):
                    info(str(panic))  # soft-skip — без спама в журнал
                    debug("Возврат к списку…")
                    if list_page and not list_page.is_closed():
                        await return_platcore_list_from_preview(
                            list_page, monitor_url
                        )
                    # Слот не занят — убираем временную строку прогресса
                    progress.deals = [
                        d
                        for d in progress.deals
                        if d.get("index") != next_index
                    ]
                    progress.begin_search()
                    break
                try:
                    await offer_recovery_choice(
                        panic, stage="PlatCore Accept", deal_index=next_index
                    )
                except JobStopped:
                    raise
                # Пропуск тоже занимает слот (как банк), иначе счётчик «зависает».
                spawned += 1
                empty_list_passes = 0
                picked = True
                progress.mark_skipped(next_index, "Не удалось принять")
                warn(
                    f"Сделка #{next_index} пропущена (PlatCore) — "
                    f"слот {spawned}/{max_deals}"
                )
                if list_page and not list_page.is_closed():
                    try:
                        await dismiss_chakra_toasts(list_page)
                        await return_platcore_list_from_preview(
                            list_page, monitor_url
                        )
                    except Exception as cleanup_exc:
                        info(f"Возврат к списку после пропуска: {cleanup_exc}")
                        try:
                            list_page = await ensure_platcore_list_tab(
                                context, monitor_url, reuse_existing=False
                            )
                        except Exception:
                            list_page = None
                break

            accepted_deals.append(accepted)
            spawned += 1
            empty_list_passes = 0
            list_page = None
            picked = True
            progress.mark_accepted(accepted)

            bank_ok = await pay_accepted_deal(
                accepted, cfg, progress=progress
            )
            if not bank_ok:
                list_page = None
                break

            keep_pages = [
                a.platcore_page for a in accepted_deals if a.platcore_page
            ]
            await close_stale_tabs(context, keep_pages)

            if spawned < max_deals and spawn_delay > 0:
                debug(f"Пауза {spawn_delay:g} с")
                progress.notify(
                    phase="processing",
                    message=(
                        f"Пауза {spawn_delay:g} с. "
                        f"Выплачено {len(accepted_deals)} из {max_deals}. "
                        f"Ищу следующую…"
                    ),
                )
                await asyncio.sleep(spawn_delay)

            if spawned < max_deals and confirm_next:
                from ui.prompts import wait_user_confirm

                await wait_user_confirm(
                    f"\n[INFO] Enter — следующая сделка "
                    f"({spawned}/{max_deals} готово): "
                )
            elif spawned < max_deals:
                progress.begin_search()
            break

        if not picked:
            wrapped = False
            if list_page and not list_page.is_closed():
                # False = дошли до конца списка и вернулись наверх (полный круг).
                still_scrolling = await nudge_platcore_list_scroll(list_page)
                wrapped = not still_scrolling
            if wrapped:
                empty_list_passes += 1
                info(
                    f"Список просмотрен без новой сделки "
                    f"(круг {empty_list_passes}/{max_empty_passes}), "
                    f"принято {len(accepted_deals)}/{max_deals}"
                )
                if empty_list_passes >= max_empty_passes:
                    warn(
                        f"Новых подходящих сделок нет после {empty_list_passes} кругов — "
                        f"завершаю Accept ({len(accepted_deals)}/{max_deals}) и иду дальше"
                    )
                    progress.notify(
                        phase="processing",
                        message=(
                            f"Список исчерпан: {len(accepted_deals)} из {max_deals}. "
                            f"Перехожу дальше…"
                        ),
                    )
                    break
            await asyncio.sleep(dash_cfg.get("poll_interval_sec", 2.0))

    ok(f"Accept завершён: {len(accepted_deals)}/{max_deals}")
    progress.finish()

    keep_pages = [a.platcore_page for a in accepted_deals if a.platcore_page]
    await close_stale_tabs(context, keep_pages)

    page_by_order: dict[str, Page] = {}
    for accepted in accepted_deals:
        page = accepted.platcore_page
        if page is not None and not page.is_closed() and accepted.order_id:
            page_by_order[accepted.order_id] = page

    return accepted_deals, page_by_order
