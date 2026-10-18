"""Отмена без чека HTTP: POST /api/disputes/v2 (как фронт PlatCore)."""

from __future__ import annotations

import asyncio
import re

from core.logkit import info, ok, section
from core.validators import PanicError
from platcore.api_client import api_base_url, post_dispute, resolve_token
from platcore.dispute import DisputeConfig

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def pick_dispute_deal_id(task_id: str, order_id: str) -> str:
    """UUID для POST /disputes. У API это _id, у pending — order_id со страницы."""
    for raw in (task_id, order_id):
        value = str(raw or "").strip()
        if _UUID_RE.match(value):
            return value
    return ""


async def dispute_deal_via_api(
    cfg: dict,
    *,
    order_id: str,
    task_id: str,
    dispute: DisputeConfig,
    deal_index: int | None = None,
    base_url: str | None = None,
) -> None:
    """POST /api/disputes/v2 — reason + text из config, без браузера."""
    deal_uuid = pick_dispute_deal_id(task_id, order_id)
    if not deal_uuid:
        raise PanicError("API dispute: нет uuid сделки")
    oid = (order_id or "").strip()
    if not oid:
        raise PanicError("API dispute: нет order_id")
    if not dispute.topic:
        raise PanicError("API dispute: dispute_topic пустой")
    if not dispute.message:
        raise PanicError("API dispute: dispute_message пустой")

    prefix = f"#{deal_index} " if deal_index else ""
    section(f"{prefix}API dispute {oid}")
    info(f"  uuid   : {deal_uuid}")
    info(f"  reason : {dispute.topic!r}")
    info(f"  text   : {dispute.message!r}")

    if dispute.fake_submit:
        ok(f"{prefix}fake_dispute: POST /api/disputes/v2 не шлём")
        return

    base_url = str(base_url or api_base_url(cfg)).rstrip("/")
    token = await resolve_token(cfg, base_url)
    code = await asyncio.to_thread(
        post_dispute,
        base_url,
        token,
        deal_uuid,
        reason=dispute.topic,
        text=dispute.message,
    )
    if code not in (200, 201):
        raise PanicError(f"POST /api/disputes/v2 {deal_uuid}: HTTP {code}")
    ok(f"{prefix}API dispute {oid} → {code}")
