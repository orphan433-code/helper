"""Закрытие сделки HTTP: ledger paid=1 → PUT /upload → PUT /approve."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from completion.hz_card import activ_brand_label, render_from_ledger, save_hz_card
from core.logkit import info, ok, section
from core.paths import RUNTIME_DIR
from core.validators import PanicError
from platcore.api_client import (
    api_base_url,
    fetch_hz_ledger,
    ledger_paid_payload,
    post_hz_ledger,
    put_approve,
    put_upload,
    resolve_token,
)


def _progress(cb: Callable[..., None] | None, msg: str) -> None:
    if cb is not None:
        cb(msg)


async def complete_deal_via_api(
    *,
    task_id: str,
    order_id: str,
    account_digits: str,
    holder_name: str,
    proof: Path,
    video: Path | None,
    ledger: dict[str, Any] | None,
    cfg: dict,
    fake_money_sent: bool = False,
    give_fiat: str = "",
    on_progress: Callable[..., None] | None = None,
) -> str:
    if not task_id:
        raise PanicError("API complete: нет deal uuid")
    if not order_id:
        raise PanicError("API complete: нет order_id")
    proof = Path(proof)
    if not proof.is_file():
        raise PanicError(f"API complete: нет чека {proof}")

    base_url = api_base_url(cfg)
    token = await resolve_token(cfg, base_url)

    record = dict(ledger or {})
    if not (record.get("tjs") and record.get("give_amt")):
        fetched = await asyncio.to_thread(fetch_hz_ledger, base_url, None, order_id)
        record = dict(fetched or {})
    if not (record.get("tjs") and record.get("give_amt")):
        raise PanicError(f"API complete: ledger пуст deal={order_id}")

    brand = activ_brand_label(account_digits)
    card_img = render_from_ledger(record, card_digits=account_digits)
    hz_path = save_hz_card(RUNTIME_DIR / f"hz_{order_id}.png", card_img)

    parts: list[Path] = []
    if video is not None:
        video = Path(video)
        if not video.is_file():
            raise PanicError(f"API complete: нет видео {video}")
        parts.append(video)
    parts.append(proof)
    parts.append(hz_path)

    section(f"API Money sent {order_id}")
    info(f"  uuid      : {task_id}")
    info(f"  I give    : {record.get('give_amt')} {str(record.get('give_cur') or '').upper()}")
    info(f"  Activ     : {record.get('tjs')} TJS  ({brand})")
    for path in parts:
        info(f"  файл      : {path.name}  ({path.stat().st_size} байт)")

    if fake_money_sent:
        ok("fake_money_sent: PUT /upload и /approve не шлём")
        return "ok"

    payload = ledger_paid_payload(
        record,
        holder=holder_name,
        give_fiat=give_fiat,
    )
    _progress(on_progress, "POST /_hz/ledger paid=1")
    await asyncio.to_thread(post_hz_ledger, base_url, token, payload)

    _progress(on_progress, f"PUT /upload ({len(parts)} файл)")
    uploaded = await asyncio.to_thread(put_upload, base_url, token, parts)
    file_ids = [str(item.get("id") or "") for item in uploaded]
    for item in uploaded:
        info(
            f"  id {item.get('id')}  {item.get('type')}  "
            f"{item.get('fileName') or item.get('url')}"
        )

    _progress(on_progress, "PUT /approve")
    await asyncio.to_thread(put_approve, base_url, token, task_id, file_ids)
    ok(f"API approve {order_id}: {len(file_ids)} файл(ов)")
    return "confirmed"
