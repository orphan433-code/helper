"""Accept через API, суммы только из GET /_hz/ledger — без своего расчёта.

Включается api_flow.enabled. Старый клик-Accept не трогает.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from playwright.async_api import BrowserContext, Page

from core.deal_bridge import save_pending_deal
from core.logkit import info, ok, section, warn
from core.models import RowPreview, TzkDeal
from core.validators import (
    PanicError,
    deal_to_dict,
    session_requisites_key,
    skip_reason_for_card_brand,
)
from platcore.api_client import (
    fetch_deal_buy,
    fetch_find_new_rows,
    fetch_hz_ledger,
    origin_from_page,
    put_accept,
)
from platcore.list import wait_for_list
from platcore.pipeline import (
    AcceptedDeal,
    _validation_amount_limits,
    _validation_card_brands,
    ensure_platcore_list_tab,
    format_deal_brief,
)
from ui.job_control import JobStopped, raise_if_stopped
from ui.progress import PipelineProgressTracker

_LEDGER_WAIT_SEC = 25.0
_LEDGER_POLL_SEC = 0.6


def _api_flow_cfg(cfg: dict) -> dict:
    raw = cfg.get("api_flow") or {}
    return raw if isinstance(raw, dict) else {}


def _num(raw: Any) -> float:
    text = str(raw or "").strip().replace(" ", "").replace(",", "")
    if not text:
        return 0.0
    return float(Decimal(text))


def _row_card(row: dict[str, Any]) -> str:
    cred = row.get("credentials") or {}
    return str(cred.get("accountNumber") or "").strip()


def _row_holder(row: dict[str, Any]) -> str:
    cred = row.get("credentials") or {}
    return str(cred.get("ownerName") or "").strip()


def _row_usdt(row: dict[str, Any]) -> float:
    return _num(row.get("amount"))


def _row_fiat_code(row: dict[str, Any]) -> str:
    to = row.get("currencyTo") or {}
    return str(to.get("code") or "").strip().upper()


def _row_fiat_client(row: dict[str, Any]) -> float:
    out = row.get("out") or {}
    return _num(out.get("client"))


def _allow_currencies(flow: dict) -> list[str]:
    raw = flow.get("currencies") or []
    return [str(x).strip().upper() for x in raw if str(x).strip()]


def _skip_row(
    row: dict[str, Any],
    *,
    min_amount: float | None,
    max_amount: float | None,
    allow_visa: bool,
    allow_mc: bool,
    currencies: list[str],
    requisites_in_run: dict[str, int],
) -> str | None:
    usdt = _row_usdt(row)
    if min_amount is not None and usdt < min_amount:
        return f"USDT {usdt:g} < минимума {min_amount:g}"
    if max_amount is not None and usdt > max_amount:
        return f"USDT {usdt:g} > лимита {max_amount:g}"
    card = _row_card(row)
    skip_card = skip_reason_for_card_brand(
        card, allow_visa=allow_visa, allow_mastercard=allow_mc
    )
    if skip_card:
        return skip_card
    code = _row_fiat_code(row)
    if currencies and code not in currencies:
        return f"валюта {code or '—'} не в фильтре ({', '.join(currencies)})"
    holder = _row_holder(row)
    key = session_requisites_key(card, holder)
    prev = requisites_in_run.get(key)
    if prev is not None:
        return f"дубль реквизитов уже в #{prev}"
    return None


def _pending_deal_url(page: Page, deal_id: str) -> str:
    origin = origin_from_page(page)
    parsed = urlparse(f"{origin}/pay-out")
    query = urlencode({"limit": 100, "status": "pending", "dealId": deal_id})
    return urlunparse(parsed._replace(query=query))


def _preview_from_row(row: dict[str, Any]) -> RowPreview:
    card = _row_card(row)
    fiat = _row_fiat_client(row)
    code = _row_fiat_code(row)
    usdt = _row_usdt(row)
    return RowPreview(
        fingerprint=str(row.get("_id") or ""),
        time_text="",
        amount_raw=f"{fiat:g} {code}".strip(),
        account_raw=card,
        holder_raw=_row_holder(row),
        payment_method=str((row.get("bank") or {}).get("name") or ""),
        amount_usdt_raw=f"{usdt:g}",
    )


def _deal_from_ledger(
    *,
    row: dict[str, Any],
    buy: dict[str, Any],
    ledger: dict[str, Any],
) -> tuple[TzkDeal, str, str, str]:
    """TzkDeal + точные строки tjs / give_amt / give_cur из ledger."""
    cred = buy.get("credentials") or row.get("credentials") or {}
    card = str(cred.get("accountNumber") or _row_card(row)).strip()
    holder = str(cred.get("ownerName") or _row_holder(row)).strip()
    if not card or not holder:
        raise PanicError("API Accept: в /buy нет карты или имени")

    tjs_raw = str(ledger.get("tjs") or "").strip()
    give_raw = str(ledger.get("give_amt") or "").strip()
    give_cur = str(ledger.get("give_cur") or "").strip().lower()
    if not tjs_raw or not give_raw or give_cur not in ("eur", "usd"):
        raise PanicError(
            f"API Accept: ledger без TJS/give (tjs={tjs_raw!r} "
            f"give={give_raw!r} {give_cur!r})"
        )

    tjs = _num(tjs_raw)
    give = _num(give_raw)
    if tjs <= 0 or give <= 0:
        raise PanicError(f"API Accept: нулевые суммы ledger tjs={tjs_raw} give={give_raw}")

    fiat_code = _row_fiat_code(row) or str(
        (buy.get("currencyTo") or {}).get("code") or ""
    ).upper()
    fiat_amt = _row_fiat_client(row)
    if fiat_amt <= 0:
        fiat_amt = _num((buy.get("out") or {}).get("client"))

    order_id = str(
        ledger.get("deal_id") or row.get("orderId") or buy.get("orderId") or ""
    )
    deal = TzkDeal(
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
    return deal, tjs_raw, give_raw, give_cur.upper()


def print_bank_preview(
    *,
    index: int,
    deal: TzkDeal,
    tjs_raw: str,
    give_raw: str,
    give_cur: str,
    order_id: str,
) -> None:
    last4 = deal.account_digits[-4:] if len(deal.account_digits) >= 4 else "????"
    info("")
    section(f"Банк (сверить руками) #{index}")
    info(f"  order     : {order_id}")
    info(f"  карта     : *{last4}  ({deal.account_digits})")
    info(f"  имя       : {deal.holder_name}")
    info(f"  ввод      : {tjs_raw} TJS")
    info(f"  сверка    : {give_raw} {give_cur}")
    info("  источник  : GET /_hz/ledger (как на экране, без пересчёта)")
    info("")


async def _wait_ledger(page: Page, order_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + _LEDGER_WAIT_SEC
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        raise_if_stopped()
        rec = await fetch_hz_ledger(page, order_id)
        last = rec
        if rec and str(rec.get("tjs") or "").strip() and str(rec.get("give_amt") or "").strip():
            return rec
        await asyncio.sleep(_LEDGER_POLL_SEC)
    raise PanicError(
        f"API Accept: /_hz/ledger пуст за {_LEDGER_WAIT_SEC:g} с "
        f"(deal={order_id}, last={last!r})"
    )


async def _open_pending_for_ledger(page: Page, deal_id: str) -> None:
    url = _pending_deal_url(page, deal_id)
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(800)


async def accept_one_via_api(
    page: Page,
    row: dict[str, Any],
    *,
    cfg: dict,
    deal_index: int,
    requisites_in_run: dict[str, int],
    fake_accept: bool,
) -> AcceptedDeal:
    deal_id = str(row.get("_id") or "")
    order_id = str(row.get("orderId") or "")
    if not deal_id or not order_id:
        raise PanicError("API Accept: в findNew нет _id/orderId")

    card = _row_card(row)
    holder = _row_holder(row)
    key = session_requisites_key(card, holder)

    if fake_accept:
        warn("fake_accept: PUT /accept не отправляем, ledger не будет")
        preview = _preview_from_row(row)
        deal = TzkDeal(
            task_id=deal_id,
            account_raw=card,
            account_digits="".join(ch for ch in card if ch.isdigit()),
            holder_name=holder,
            amount_check=_row_fiat_client(row),
            amount_check_currency=_row_fiat_code(row),
            amount_tjs=0.0,
            amount_eur=0.0,
            payment_method=str((row.get("bank") or {}).get("name") or ""),
            order_id=order_id,
        )
        requisites_in_run[key] = deal_index
        info(f"  карта *{deal.account_digits[-4:]} {holder} — без сумм банка")
        return AcceptedDeal(
            index=deal_index,
            deal=deal,
            order_id=order_id,
            fingerprint=deal_id,
            data=deal_to_dict(deal),
            platcore_page=page,
            amount_usdt=_row_usdt(row),
        )

    code = await put_accept(page, deal_id)
    if code not in (200, 204):
        raise PanicError(f"PUT /accept {deal_id}: HTTP {code}")
    ok(f"PUT /accept {deal_id} → {code}")

    await _open_pending_for_ledger(page, deal_id)
    ledger = await _wait_ledger(page, order_id)
    buy = await fetch_deal_buy(page, deal_id)
    deal, tjs_raw, give_raw, give_cur = _deal_from_ledger(
        row=row, buy=buy, ledger=ledger
    )
    requisites_in_run[key] = deal_index
    save_pending_deal(deal, order_id=order_id, amount_eur_source="GET /_hz/ledger")
    print_bank_preview(
        index=deal_index,
        deal=deal,
        tjs_raw=tjs_raw,
        give_raw=give_raw,
        give_cur=give_cur,
        order_id=order_id,
    )
    accepted = AcceptedDeal(
        index=deal_index,
        deal=deal,
        order_id=order_id,
        fingerprint=deal_id,
        data=deal_to_dict(deal),
        platcore_page=page,
        amount_usdt=_row_usdt(row),
    )
    ok(f"Accept API: {format_deal_brief(accepted)}")
    return accepted


async def accept_deals_loop_api(
    context: BrowserContext, cfg: dict
) -> tuple[list[AcceptedDeal], dict[str, Page]]:
    dash_cfg = cfg["dashboard"]
    pipe_cfg = cfg.get("pipeline") or {}
    flow = _api_flow_cfg(cfg)
    val_cfg = cfg["validation"]
    stage1 = cfg.get("stage1") or {}

    max_deals = int(flow.get("max_deals") or 1)
    max_empty_passes = max(1, int(pipe_cfg.get("max_empty_list_passes", 2)))
    spawn_delay = float(pipe_cfg.get("spawn_deal_delay_sec", 2.0))
    fake_accept = bool(stage1.get("fake_accept", False))
    poll_sec = float(dash_cfg.get("poll_interval_sec", 2.0))
    min_amount, max_amount = _validation_amount_limits(val_cfg)
    allow_visa, allow_mc = _validation_card_brands(val_cfg)
    currencies = _allow_currencies(flow)
    monitor_url = dash_cfg["monitor_url"]

    section(
        f"API Accept: до {max_deals} (клик-Accept выкл, банк/чеки этого флоу пока нет)"
    )
    if currencies:
        info(f"Валюты: {', '.join(currencies)}")
    else:
        info("Валюты: все (фильтр api_flow.currencies пуст)")
    if fake_accept:
        warn("fake_accept — PUT не уйдёт")

    page = await ensure_platcore_list_tab(context, monitor_url, reuse_existing=True)
    await wait_for_list(page)

    seen: set[str] = set()
    if not dash_cfg.get("process_existing_on_start", False):
        existing = await fetch_find_new_rows(page, status="new")
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

    while spawned < max_deals:
        raise_if_stopped()
        if page.is_closed():
            page = await ensure_platcore_list_tab(context, monitor_url)
        rows = await fetch_find_new_rows(page, status="new")
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
                currencies=currencies,
                requisites_in_run=requisites_in_run,
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
            info(f"API Accept #{next_index}: {deal_id} {_row_fiat_code(row)}")
            try:
                accepted = await accept_one_via_api(
                    page,
                    row,
                    cfg=cfg,
                    deal_index=next_index,
                    requisites_in_run=requisites_in_run,
                    fake_accept=fake_accept,
                )
            except JobStopped:
                raise
            except Exception as exc:
                warn(f"API Accept fail: {exc}")
                progress.mark_skipped(next_index, str(exc)[:80])
                spawned += 1
                empty_passes = 0
                picked = True
                try:
                    await page.goto(monitor_url, wait_until="domcontentloaded")
                    await wait_for_list(page)
                except Exception:
                    pass
                break

            accepted_deals.append(accepted)
            progress.mark_accepted(accepted)
            spawned += 1
            empty_passes = 0
            picked = True
            if spawned < max_deals and spawn_delay > 0:
                await page.goto(monitor_url, wait_until="domcontentloaded")
                await wait_for_list(page)
                await asyncio.sleep(spawn_delay)
            break

        if picked:
            continue
        empty_passes += 1
        info(f"Пустой круг findNew {empty_passes}/{max_empty_passes}")
        if empty_passes >= max_empty_passes:
            break
        await asyncio.sleep(poll_sec)

    ok(f"API Accept готов: {len(accepted_deals)}/{max_deals}")
    page_by_order = {
        a.order_id: a.platcore_page
        for a in accepted_deals
        if a.platcore_page is not None
    }
    return accepted_deals, page_by_order
