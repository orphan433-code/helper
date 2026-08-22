"""Accept через HTTP, как редирект. Суммы только из GET /_hz/ledger.

Включается api_flow.enabled. Старый клик-Accept не трогает. Окно не открываем.
"""

from __future__ import annotations

import asyncio
import time
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from playwright.async_api import Page

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
    api_base_url,
    fetch_deal_buy,
    fetch_find_new_rows,
    fetch_hz_ledger,
    prime_hz_ledger,
    put_accept,
    resolve_token,
)
from core.name_match import names_match
from platcore.pipeline import (
    AcceptedDeal,
    _validation_amount_limits,
    _validation_card_brands,
    format_deal_brief,
    pay_accepted_deal,
)
from ui.job_control import JobStopped, raise_if_stopped
from ui.progress import PipelineProgressTracker

_LEDGER_WAIT_SEC = 45.0
_LEDGER_POLL_SEC = 1.2


def _api_flow_cfg(cfg: dict) -> dict:
    raw = cfg.get("api_flow") or {}
    return raw if isinstance(raw, dict) else {}


def _num(raw: Any) -> float:
    if raw is None or raw is False:
        return 0.0
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        if "value" in raw:
            return _num(raw.get("value"))
        if "record" in raw:
            return _num(raw.get("record"))
        for key in ("fx", "amount_usd", "rate"):
            if key in raw:
                return _num(raw.get(key))
        return 0.0
    text = str(raw).strip().replace(" ", "").replace(",", ".")
    if not text:
        return 0.0
    try:
        return float(Decimal(text))
    except Exception:
        return 0.0


def _rate_value(rates: dict[str, Any], key: str) -> float:
    return _num(rates.get(key))


def _row_card(row: dict[str, Any]) -> str:
    cred = row.get("credentials") or {}
    return str(cred.get("accountNumber") or "").strip()


def _row_holder(row: dict[str, Any]) -> str:
    cred = row.get("credentials") or {}
    return str(cred.get("ownerName") or "").strip()


def _row_sender(row: dict[str, Any]) -> str:
    cred = row.get("credentials") or {}
    meta = row.get("metadata") or {}
    personal = cred.get("personal") if isinstance(cred.get("personal"), dict) else {}
    return str(
        cred.get("senderName")
        or meta.get("senderName")
        or personal.get("name")
        or ""
    ).strip()


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


def _money2(value: float) -> str:
    return str(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def _cents_up(value: float) -> str:
    """I give USD: 675.65043 → 675.66, как hz-calc (не banker's 675.65)."""
    cents = (Decimal(str(value)) * Decimal("100")).to_integral_value(
        rounding=ROUND_CEILING
    )
    return str((cents / Decimal("100")).quantize(Decimal("0.01")))


def _ledger_post_payload(
    *,
    row: dict[str, Any],
    buy: dict[str, Any],
    rates_body: dict[str, Any],
    eur_body: dict[str, Any],
    order_id: str,
    holder: str,
) -> dict[str, Any]:
    """Тело как hz-calc: POST /_hz/ledger. Ответ — источник для банка."""
    out = buy.get("out") or row.get("out") or {}
    eur_rec = eur_body.get("record") if isinstance(eur_body.get("record"), dict) else eur_body
    amount_usd = _num(out.get("bodyFinal")) or _num(eur_rec.get("amount_usd"))
    fiat_amt = _row_fiat_client(row) or _num(out.get("client"))
    fiat_cur = _row_fiat_code(row) or str(
        (buy.get("currencyTo") or {}).get("code") or ""
    ).upper()
    rates = rates_body.get("rates") or {}
    if not isinstance(rates, dict):
        rates = {}
    activ_usd = _rate_value(rates, "activ.usd")
    activ_eur = _rate_value(rates, "activ.eur")
    xe = _num(eur_rec.get("fx"))

    # Виджет по умолчанию — I give USD. EUR только если выплата уже EUR.
    # xe из /_hz/eur всегда есть — из‑за него ушли в 572.29 EUR, на экране было USD.
    if fiat_cur == "EUR" and fiat_amt > 0:
        give_cur = "eur"
        give_amt = _money2(fiat_amt)
        rate = activ_eur
    else:
        give_cur = "usd"
        give_amt = _cents_up(amount_usd)
        rate = activ_usd
        xe = 0.0

    tjs = _money2(_num(give_amt) * rate)
    payload: dict[str, Any] = {
        "deal_id": order_id,
        "account": holder,
        "amount_usd": amount_usd,
        "give_fiat": f"{_money2(fiat_amt)} {fiat_cur}".strip(),
        "bank": "activ",
        "give_cur": give_cur,
        "give_amt": give_amt,
        "tjs": tjs,
        "rate": rate,
        "alif_cur": "usd",
        "paid": 0,
    }
    if xe > 0:
        payload["xe"] = xe
    return payload


def print_buy_dump(row: dict[str, Any], buy: dict[str, Any]) -> None:
    cred = buy.get("credentials") or row.get("credentials") or {}
    out = buy.get("out") or {}
    amounts = buy.get("amounts") or {}
    digits = "".join(ch for ch in str(cred.get("accountNumber") or "") if ch.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else "????"
    section("GET /buy (после accept)")
    info(f"  order     : {row.get('orderId') or buy.get('orderId')}")
    info(f"  карта     : *{last4}  {digits}")
    info(f"  имя       : {cred.get('ownerName') or '—'}")
    info(f"  client    : {out.get('client')}")
    info(f"  bodyFinal : {out.get('bodyFinal')}")
    info(f"  fiat_net  : {amounts.get('fiat_net')}")
    info("")


def print_bank_preview(
    *,
    index: int,
    deal: TzkDeal,
    tjs_raw: str,
    give_raw: str,
    give_cur: str,
    order_id: str,
    fiat_raw: str = "",
    usdt_raw: str = "",
) -> None:
    last4 = deal.account_digits[-4:] if len(deal.account_digits) >= 4 else "????"
    info("")
    section(f"В банк (сверь с hz-calc в своём UI) #{index}")
    info(f"  order     : {order_id}")
    if fiat_raw or usdt_raw:
        info(f"  список    : {fiat_raw or '—'}  /  {usdt_raw or '—'} USDT")
    info(f"  карта     : *{last4}  {deal.account_digits}")
    info(f"  имя       : {deal.holder_name}")
    info(f"  ВВОД      : {tjs_raw} TJS")
    info(f"  СВЕРКА    : {give_raw} {give_cur}")
    info("  источник  : GET /_hz/ledger (без токена)")
    info("")


async def _wait_ledger(
    base_url: str, token: str | None, order_id: str
) -> dict[str, Any]:
    deadline = time.monotonic() + _LEDGER_WAIT_SEC
    last: dict[str, Any] | None = None
    warned = False
    while time.monotonic() < deadline:
        raise_if_stopped()
        rec = await asyncio.to_thread(fetch_hz_ledger, base_url, token, order_id)
        last = rec
        if rec and str(rec.get("tjs") or "").strip() and str(rec.get("give_amt") or "").strip():
            return rec
        if not warned:
            info("Жду GET /_hz/ledger")
            warned = True
        await asyncio.sleep(_LEDGER_POLL_SEC)
    warn(
        f"GET /_hz/ledger пуст за {_LEDGER_WAIT_SEC:g} с (deal={order_id})"
    )
    return last or {}


async def accept_one_via_api(
    base_url: str,
    token: str,
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
        warn("fake_accept: PUT /accept не отправляем")
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
            platcore_page=None,
            amount_usdt=_row_usdt(row),
        )

    if not bool((_api_flow_cfg(cfg)).get("accept", True)):
        raise PanicError("api_flow.accept=false — PUT выкл")

    code = await asyncio.to_thread(put_accept, base_url, token, deal_id)
    if code not in (200, 204):
        raise PanicError(f"PUT /accept {deal_id}: HTTP {code}")
    ok(f"PUT /accept {order_id} → {code}")

    buy = await asyncio.to_thread(fetch_deal_buy, base_url, token, deal_id)
    print_buy_dump(row, buy)
    # GET без записи = {"record":null}. Пишет фронт POST /_hz/ledger — не мы.
    await prime_hz_ledger(cfg, base_url, deal_id, token, order_id)
    ledger = await asyncio.to_thread(fetch_hz_ledger, base_url, None, order_id)
    if not (ledger and ledger.get("tjs") and ledger.get("give_amt")):
        ledger = await _wait_ledger(base_url, None, order_id)
    if not (ledger and ledger.get("tjs") and ledger.get("give_amt")):
        raise PanicError(
            f"GET /_hz/ledger?deal={order_id} record=null — фронт не записал POST"
        )
    deal, tjs_raw, give_raw, give_cur = _deal_from_ledger(
        row=row, buy=buy, ledger=ledger
    )
    requisites_in_run[key] = deal_index
    save_pending_deal(deal, order_id=order_id, amount_eur_source="GET /_hz/ledger")
    fiat_amt = deal.amount_check
    fiat_cur = deal.amount_check_currency or ""
    ledger_snap = {
        **ledger,
        "account": holder or ledger.get("account") or "",
        "give_fiat": ledger.get("give_fiat")
        or f"{_money2(fiat_amt)} {fiat_cur}".strip(),
        "deal_id": ledger.get("deal_id") or order_id,
    }
    print_bank_preview(
        index=deal_index,
        deal=deal,
        tjs_raw=tjs_raw,
        give_raw=give_raw,
        give_cur=give_cur,
        order_id=order_id,
        fiat_raw=f"{fiat_amt:g} {fiat_cur}".strip(),
        usdt_raw=f"{_row_usdt(row):g}",
    )
    accepted = AcceptedDeal(
        index=deal_index,
        deal=deal,
        order_id=order_id,
        fingerprint=deal_id,
        data=deal_to_dict(deal),
        platcore_page=None,
        amount_usdt=_row_usdt(row),
        ledger=ledger_snap,
    )
    ok(f"Accept API: {format_deal_brief(accepted)}")
    return accepted


async def accept_deals_loop_api(
    cfg: dict,
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

    base_url = api_base_url(cfg)
    token = await resolve_token(cfg, base_url)
    info(f"Токен ок, HTTP {base_url}")

    section(f"API Accept: {max_deals} сделка, PUT /accept")
    if currencies:
        info(f"Валюты: {', '.join(currencies)}")
    if fake_accept:
        warn("fake_accept — PUT не уйдёт")

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
            info(f"API Accept #{next_index}: {row.get('orderId')} {_row_fiat_code(row)}")
            try:
                accepted = await accept_one_via_api(
                    base_url,
                    token,
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
                break

            accepted_deals.append(accepted)
            progress.mark_accepted(accepted)
            bank_ok = True
            if bool(flow.get("run_bank")):
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

    ok(f"API Accept готов: {len(accepted_deals)}/{max_deals}")
    return accepted_deals, {}


def _ui_deal_row(row: dict[str, Any], *, ok_flag: bool, error: str = "") -> dict[str, Any]:
    card = _row_card(row)
    last4 = card[-4:] if len(card) >= 4 else "????"
    usdt = _row_usdt(row)
    fiat = _row_fiat_client(row)
    code = _row_fiat_code(row)
    amount = f"{fiat:g} {code}".strip() if fiat else f"{usdt:g} USDT"
    return {
        "order_id": str(row.get("orderId") or ""),
        "card": f"*{last4}",
        "holder": _row_holder(row),
        "amount": amount,
        "bank": _row_sender(row),
        "ok": bool(ok_flag),
        "error": (error or "").strip(),
    }


async def accept_matching_names_loop(
    cfg: dict,
    *,
    max_deals: int,
    min_amount: float | None = None,
    max_amount: float | None = None,
) -> dict[str, Any]:
    """Только PUT /accept: owner ≈ sender, фильтр USDT. Банк/чеки не трогаем."""
    dash_cfg = cfg.get("dashboard") or {}
    pipe_cfg = cfg.get("pipeline") or {}
    want = max(1, min(50, int(max_deals)))
    max_empty_passes = max(1, int(pipe_cfg.get("max_empty_list_passes", 2)))
    poll_sec = float(dash_cfg.get("poll_interval_sec", 2.0))
    spawn_delay = float(pipe_cfg.get("spawn_deal_delay_sec", 0.4))

    base_url = api_base_url(cfg)
    token = await resolve_token(cfg, base_url)
    info(f"Токен ок, HTTP {base_url}")
    amt_bits = []
    if min_amount is not None:
        amt_bits.append(f">= {min_amount:g}")
    if max_amount is not None:
        amt_bits.append(f"<= {max_amount:g}")
    amt_note = f", USDT {' и '.join(amt_bits)}" if amt_bits else ""
    section(f"Accept по именам: до {want} шт.{amt_note} · только PUT /accept")

    seen: set[str] = set()
    deals_ui: list[dict[str, Any]] = []
    done_ok = 0
    failed = 0
    empty_passes = 0

    while done_ok + failed < want:
        raise_if_stopped()
        rows = await asyncio.to_thread(fetch_find_new_rows, base_url, token)
        picked = False
        for row in rows:
            deal_id = str(row.get("_id") or "")
            if not deal_id or deal_id in seen:
                continue
            seen.add(deal_id)
            owner = _row_holder(row)
            sender = _row_sender(row)
            if not names_match(owner, sender):
                info(
                    f"Пропуск имён: {owner or '—'} ≠ {sender or '—'} "
                    f"({row.get('orderId')})"
                )
                continue
            usdt = _row_usdt(row)
            if min_amount is not None and usdt < min_amount:
                info(
                    f"Пропуск USDT {usdt:g} < {min_amount:g} ({row.get('orderId')})"
                )
                continue
            if max_amount is not None and usdt > max_amount:
                info(
                    f"Пропуск USDT {usdt:g} > {max_amount:g} ({row.get('orderId')})"
                )
                continue

            order_id = str(row.get("orderId") or "")
            info(f"Accept #{done_ok + failed + 1}: {order_id} {owner} = {sender}")
            try:
                code = await asyncio.to_thread(put_accept, base_url, token, deal_id)
                if code not in (200, 204):
                    raise PanicError(f"PUT /accept HTTP {code}")
                ok(f"PUT /accept {order_id} → {code}")
                done_ok += 1
                deals_ui.append(_ui_deal_row(row, ok_flag=True))
            except JobStopped:
                raise
            except Exception as exc:
                warn(f"Accept fail {order_id}: {exc}")
                failed += 1
                deals_ui.append(_ui_deal_row(row, ok_flag=False, error=str(exc)[:160]))
            picked = True
            if done_ok + failed < want and spawn_delay > 0:
                await asyncio.sleep(spawn_delay)
            break

        if picked:
            empty_passes = 0
            continue
        empty_passes += 1
        info(f"Пустой круг findNew {empty_passes}/{max_empty_passes}")
        if empty_passes >= max_empty_passes:
            break
        await asyncio.sleep(poll_sec)

    total = done_ok + failed
    if total == 0:
        msg = "Подходящих сделок (owner = sender) нет"
    elif failed:
        msg = f"Принято {done_ok} из {total}, с ошибкой {failed}"
    else:
        msg = f"Принято {done_ok} из {total}"
    ok(msg)
    return {
        "phase": "done",
        "action": "accept",
        "accepted": done_ok,
        "cancelled": 0,
        "redirected": 0,
        "failed": failed,
        "total": total,
        "title": "Принято" if done_ok else "Принятие",
        "message": msg,
        "deals": deals_ui,
    }

