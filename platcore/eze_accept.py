"""EasySend accept: курсы Activ OCR, без HZ ledger / hz-calc."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from bank.activ_rates import ActivRates, wait_for_activ_rates
from core.deal_bridge import save_pending_deal
from core.deals_ui_local import (
    pipeline_ui_bin_prefixes,
    pipeline_ui_dry_stop,
    pipeline_ui_skip_bog,
    pipeline_ui_skip_tbc,
)
from core.decline_hosts import DECLINE_SERVICE_EZE, DECLINE_SERVICE_URLS
from core.logkit import info, ok, section, warn
from core.models import TzkDeal
from core.validators import (
    PanicError,
    deal_to_dict,
    ignored_bank_prefixes,
    session_requisites_key,
)
from platcore.api_accept import (
    _preview_from_row,
    _row_card,
    _row_fiat_client,
    _row_fiat_code,
    _row_holder,
    _row_usdt,
    _skip_row,
    print_buy_dump,
)
from platcore.api_client import (
    fetch_deal_buy,
    fetch_find_new_rows,
    put_accept,
    resolve_token,
)
from platcore.eze_amounts import (
    card_scheme,
    money2,
    tjs_for_mc_eur,
    tjs_for_visa,
)
from platcore.eze_xe import gel_to_eur, xe_shot_path
from platcore.pipeline import (
    AcceptedDeal,
    _validation_amount_limits,
    _validation_card_brands,
    format_deal_brief,
    pay_accepted_deal,
)
from ui.job_control import JobStopped, raise_if_stopped
from ui.progress import PipelineProgressTracker
from ui.prompts import wait_user_confirm

_EZE_ACCEPT_OK = frozenset({200, 204})
_EZE_ACCEPT_LIE = frozenset({400, 409})


def _row_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("_id") or "") for row in rows if row.get("_id")}


def eze_accept_looks_taken(
    deal_id: str,
    *,
    pending_ids: set[str],
    new_ids: set[str],
) -> bool:
    """EasySend часто отвечает 400, хотя PUT /accept уже прошёл."""
    if not deal_id:
        return False
    if deal_id in pending_ids:
        return True
    if deal_id in new_ids:
        return False
    return True


async def confirm_eze_put_accept(
    base_url: str,
    token: str,
    *,
    deal_id: str,
    order_id: str,
) -> None:
    code = await asyncio.to_thread(put_accept, base_url, token, deal_id)
    if code in _EZE_ACCEPT_OK:
        ok(f"EZE PUT /accept {order_id} → {code}")
        return
    if code in _EZE_ACCEPT_LIE:
        warn(f"EZE PUT /accept {order_id} HTTP {code} — проверяю pending/new")
        pending = await asyncio.to_thread(
            fetch_find_new_rows, base_url, token, status="pending"
        )
        news = await asyncio.to_thread(
            fetch_find_new_rows, base_url, token, status="new"
        )
        if eze_accept_looks_taken(
            deal_id,
            pending_ids=_row_ids(pending),
            new_ids=_row_ids(news),
        ):
            warn(
                f"EZE соврала HTTP {code}, сделка {order_id} принята — едем дальше"
            )
            return
    raise PanicError(f"PUT /accept {deal_id}: HTTP {code}")


async def capture_session_rates(*, timeout_sec: float = 180.0) -> ActivRates:
    """Главная Activ: чипы RUB/USD/EUR. В банк — нижнее EUR (продажа)."""
    section("EZE: жду главную Activ с курсами")
    info("Открой главную Activ (чипы RUB / USD / EUR)")
    rates = await asyncio.to_thread(
        wait_for_activ_rates, timeout_sec=timeout_sec
    )
    info(
        f"OCR Activ: EUR продажа {rates.eur_sell:g} "
        f"(покупка {rates.eur_buy:g}), "
        f"USD продажа {rates.usd_sell:g}"
    )
    await wait_user_confirm(rates.confirm_prompt())
    ok(f"Курс сессии: 1 EUR = {rates.eur_sell:g} TJS")
    return rates


def _deal_from_eze(
    *,
    row: dict[str, Any],
    buy: dict[str, Any],
    tjs: float,
    give: float,
    give_cur: str,
) -> TzkDeal:
    cred = buy.get("credentials") or row.get("credentials") or {}
    card = str(cred.get("accountNumber") or _row_card(row)).strip()
    holder = str(cred.get("ownerName") or _row_holder(row)).strip()
    if not card or not holder:
        raise PanicError("EZE: в /buy нет карты или имени")
    fiat_code = _row_fiat_code(row) or str(
        (buy.get("currencyTo") or {}).get("code") or ""
    ).upper()
    fiat_amt = _row_fiat_client(row)
    if fiat_amt <= 0:
        out = buy.get("out") if isinstance(buy.get("out"), dict) else {}
        fiat_amt = float(out.get("client") or 0) if out else 0.0
    order_id = str(row.get("orderId") or buy.get("orderId") or "")
    return TzkDeal(
        task_id=str(row.get("_id") or ""),
        account_raw=card,
        account_digits="".join(ch for ch in card if ch.isdigit()),
        holder_name=holder,
        amount_check=fiat_amt,
        amount_check_currency=fiat_code,
        amount_tjs=tjs,
        amount_eur=give if give_cur == "eur" else 0.0,
        amount_usd=give if give_cur == "usd" else 0.0,
        payment_method=str((row.get("bank") or {}).get("name") or "card"),
        order_id=order_id,
    )


async def _give_amounts(
    row: dict[str, Any],
    rates: ActivRates,
    *,
    order_id: str,
) -> tuple[float, float, str, Path | None]:
    card = _row_card(row)
    scheme = card_scheme(card)
    fiat_code = _row_fiat_code(row)
    if scheme == "visa":
        tjs, usd = tjs_for_visa(row, rates)
        return tjs, usd, "usd", None
    if scheme != "mastercard":
        raise PanicError(f"EZE: неизвестная карта {card[:6]}…")
    if fiat_code == "EUR":
        eur = money2(_row_fiat_client(row))
        tjs, give = tjs_for_mc_eur(eur, rates)
        return tjs, give, "eur", None
    gel = _row_fiat_client(row)
    if gel <= 0:
        raise PanicError("EZE MC: нет GEL (out.client)")
    shot = xe_shot_path(order_id)
    eur = await gel_to_eur(gel, shot_path=shot)
    tjs, give = tjs_for_mc_eur(eur, rates)
    xe_path = shot if Path(shot).is_file() else None
    return tjs, give, "eur", xe_path


async def accept_one_eze(
    base_url: str,
    token: str,
    row: dict[str, Any],
    *,
    cfg: dict,
    deal_index: int,
    requisites_in_run: dict[str, int],
    rates: ActivRates,
) -> AcceptedDeal:
    deal_id = str(row.get("_id") or "")
    order_id = str(row.get("orderId") or "")
    if not deal_id or not order_id:
        raise PanicError("EZE: в findNew нет _id/orderId")

    card = _row_card(row)
    holder = _row_holder(row)
    key = session_requisites_key(card, holder)

    await confirm_eze_put_accept(
        base_url, token, deal_id=deal_id, order_id=order_id
    )

    buy = await asyncio.to_thread(fetch_deal_buy, base_url, token, deal_id)
    print_buy_dump(row, buy)
    work = dict(row)
    for field in ("out", "fees", "currencyTo", "credentials", "amounts"):
        if isinstance(buy.get(field), dict):
            work[field] = buy[field]

    tjs, give, give_cur, xe_shot = await _give_amounts(
        work, rates, order_id=order_id
    )
    deal = _deal_from_eze(
        row=work, buy=buy, tjs=tjs, give=give, give_cur=give_cur
    )
    requisites_in_run[key] = deal_index
    save_pending_deal(deal, order_id=order_id, amount_eur_source="EZE Activ OCR")
    last4 = deal.account_digits[-4:] if len(deal.account_digits) >= 4 else "????"
    info("")
    section(f"В банк (EZE OCR) #{deal_index}")
    info(f"  order     : {order_id}")
    info(
        f"  список    : {deal.amount_check:g} {deal.amount_check_currency}  /  "
        f"{_row_usdt(work):g} USDT"
    )
    info(f"  карта     : *{last4}  {deal.account_digits}")
    info(f"  имя       : {deal.holder_name}")
    info(f"  ВВОД      : {tjs:g} TJS")
    info(f"  СВЕРКА    : {give:g} {give_cur.upper()}")
    info(
        f"  источник  : Activ OCR EUR {rates.eur_sell:g} / "
        f"USD {rates.usd_sell:g}"
    )
    if xe_shot is not None:
        info(f"  XE скрин  : {xe_shot.name}")
    elif give_cur == "usd":
        info("  XE скрин  : нет (Visa — ждём чек банка)")
    else:
        info("  XE скрин  : нет")
    info("")
    ledger_snap = {
        "deal_id": order_id,
        "account": holder,
        "tjs": f"{tjs:g}",
        "give_amt": f"{give:g}",
        "give_cur": give_cur,
        "rate": rates.eur_sell if give_cur == "eur" else rates.usd_sell,
        "bank": "activ",
        "paid": 0,
        "source": "eze_ocr",
    }
    accepted = AcceptedDeal(
        index=deal_index,
        deal=deal,
        order_id=order_id,
        fingerprint=deal_id,
        data=deal_to_dict(deal),
        platcore_page=None,
        amount_usdt=_row_usdt(row),
        ledger=ledger_snap,
        extra_proofs=[xe_shot] if xe_shot is not None else None,
    )
    ok(f"EZE Accept: {format_deal_brief(accepted)}")
    return accepted


async def accept_deals_loop_eze(
    cfg: dict,
) -> tuple[list[AcceptedDeal], dict[str, Page]]:
    dash_cfg = cfg["dashboard"]
    pipe_cfg = cfg.get("pipeline") or {}
    flow = cfg.get("api_flow") or {}
    if not isinstance(flow, dict):
        flow = {}
    val_cfg = cfg["validation"]

    max_deals = int(pipe_cfg.get("max_deals_per_run") or flow.get("max_deals") or 5)
    if pipeline_ui_dry_stop():
        max_deals = 1
        info("Тест: одна сделка, стоп до SMS / оплаты")
    max_empty_passes = max(1, int(pipe_cfg.get("max_empty_list_passes", 2)))
    spawn_delay = float(pipe_cfg.get("spawn_deal_delay_sec", 2.0))
    poll_sec = float(dash_cfg.get("poll_interval_sec", 2.0))
    min_amount, max_amount = _validation_amount_limits(val_cfg)
    allow_visa, allow_mc = _validation_card_brands(val_cfg)

    base_url = DECLINE_SERVICE_URLS[DECLINE_SERVICE_EZE]
    token = await resolve_token(cfg, base_url)
    info(f"Токен ок, HTTP {base_url}")

    bin_prefixes = pipeline_ui_bin_prefixes()
    skip_tbc = pipeline_ui_skip_tbc()
    skip_bog = pipeline_ui_skip_bog()
    section(f"EZE Accept: до {max_deals} сделок, без HZ ledger")
    info("Валютный фильтр HZ (EUR/THB/TRY) не применяем")
    if skip_tbc:
        info(f"Пропуск TBC: {', '.join(p + '*' for p in ignored_bank_prefixes('tbc'))}")
    if skip_bog:
        info(f"Пропуск BOG: {', '.join(p + '*' for p in ignored_bank_prefixes('bog'))}")
    if bin_prefixes:
        info(f"BIN: только {', '.join(p + '*' for p in bin_prefixes)}")

    rates = await capture_session_rates()

    seen: set[str] = set()
    if not dash_cfg.get("process_existing_on_start", False):
        existing = await asyncio.to_thread(fetch_find_new_rows, base_url, token)
        for row in existing:
            did = str(row.get("_id") or "")
            if did:
                seen.add(did)
        if seen:
            info(f"Старт: пропуск {len(seen)} уже висящих new")

    accepted_deals: list[AcceptedDeal] = []
    requisites_in_run: dict[str, int] = {}
    spawned = 0
    empty_passes = 0
    progress = PipelineProgressTracker(total=max_deals)
    progress.begin_search()

    run_bank = True

    while spawned < max_deals:
        raise_if_stopped()
        rows = await asyncio.to_thread(fetch_find_new_rows, base_url, token)
        picked = False
        for row in rows:
            deal_id = str(row.get("_id") or "")
            if not deal_id or deal_id in seen:
                continue
            skip = _skip_row(
                row,
                min_amount=min_amount,
                max_amount=max_amount,
                allow_visa=allow_visa,
                allow_mc=allow_mc,
                bin_prefixes=bin_prefixes,
                currencies=[],
                requisites_in_run=requisites_in_run,
                skip_tbc=skip_tbc,
                skip_bog=skip_bog,
            )
            if skip:
                info(
                    f"Пропуск: {deal_id[:8]}… "
                    f"{_row_fiat_code(row)} {_row_usdt(row):g} USDT — {skip}"
                )
                seen.add(deal_id)
                continue

            seen.add(deal_id)
            next_index = spawned + 1
            preview = _preview_from_row(row)
            progress.start_accept(next_index, preview)
            info(f"EZE Accept #{next_index}: {row.get('orderId')} {_row_fiat_code(row)}")
            try:
                accepted = await accept_one_eze(
                    base_url,
                    token,
                    row,
                    cfg=cfg,
                    deal_index=next_index,
                    requisites_in_run=requisites_in_run,
                    rates=rates,
                )
            except JobStopped:
                raise
            except Exception as exc:
                warn(f"EZE Accept fail: {exc}")
                progress.mark_skipped(next_index, str(exc)[:80])
                spawned += 1
                empty_passes = 0
                picked = True
                break

            accepted_deals.append(accepted)
            progress.mark_accepted(accepted)
            bank_ok = True
            if run_bank:
                bank_ok = await pay_accepted_deal(
                    accepted, cfg, progress=progress
                )
            spawned += 1
            empty_passes = 0
            picked = True
            if not bank_ok:
                break
            if spawned < max_deals and spawn_delay > 0:
                await asyncio.sleep(spawn_delay)
            break

        if picked:
            continue
        empty_passes += 1
        info(f"Пустой круг findNew {empty_passes}/{max_empty_passes}")
        if empty_passes >= max_empty_passes:
            break
        await asyncio.sleep(poll_sec)

    ok(f"EZE Accept готов: {len(accepted_deals)}/{max_deals}")
    return accepted_deals, {}
