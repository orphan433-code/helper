"""Случайные паузы и «человечные» клики."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from playwright.async_api import Locator

from config_loader import resolve_timing_profile


@dataclass(frozen=True)
class HumanTiming:
    delay_min_sec: float
    delay_max_sec: float
    preview_highlight_sec: float
    fast_clicks: bool
    accept_wait_timeout_ms: int
    confirm_accept_timeout_ms: int
    debug_timing: bool


def parse_human_timing(cfg: dict) -> HumanTiming:
    h = cfg.get("human") or {}
    profile = resolve_timing_profile(h)
    if profile == "fast":
        delay_min, delay_max = 0.12, 0.28
        fast_clicks = True
        accept_ms, confirm_ms = 6_000, 4_000
        preview_sec = 0.0
    elif profile == "balanced":
        delay_min, delay_max = 0.18, 0.35
        fast_clicks = True
        accept_ms, confirm_ms = 8_000, 5_000
        preview_sec = 0.0
    else:
        delay_min = float(h.get("delay_min_sec", 1.0))
        delay_max = float(h.get("delay_max_sec", 2.0))
        fast_clicks = False
        accept_ms, confirm_ms = 15_000, 8_000
        preview_sec = float(h.get("preview_highlight_sec", 0.8))

    if h.get("delay_min_sec") is not None:
        delay_min = float(h["delay_min_sec"])
    if h.get("delay_max_sec") is not None:
        delay_max = float(h["delay_max_sec"])

    return HumanTiming(
        delay_min_sec=delay_min,
        delay_max_sec=delay_max,
        preview_highlight_sec=preview_sec,
        fast_clicks=fast_clicks,
        accept_wait_timeout_ms=int(h.get("accept_wait_timeout_ms", accept_ms)),
        confirm_accept_timeout_ms=int(
            h.get("confirm_accept_timeout_ms", confirm_ms)
        ),
        debug_timing=bool(h.get("debug_timing", False)),
    )


async def random_pause(min_sec: float, max_sec: float) -> None:
    if max_sec <= 0:
        return
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def _is_pointer_intercept(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "intercepts pointer events" in msg
        or "subtree intercepts pointer" in msg
        or "element is outside of the viewport" in msg
    )


async def human_click(locator: Locator, *, timing: HumanTiming) -> None:
    """Клик с паузой. При тосте Chakra — закрыть и повторить (без force)."""
    from platcore_list import dismiss_pointer_blockers, is_duplicate_deal_toast
    from validators import PanicError

    await locator.scroll_into_view_if_needed()
    if timing.fast_clicks:
        await random_pause(0.12, 0.22)
    else:
        await random_pause(timing.delay_min_sec, timing.delay_max_sec)
        await locator.hover()
        await random_pause(
            timing.delay_min_sec * 0.3,
            timing.delay_max_sec * 0.5,
        )

    click_timeout_ms = 8_000 if timing.fast_clicks else 15_000
    try:
        await locator.click(timeout=click_timeout_ms)
        return
    except Exception as first:
        if not _is_pointer_intercept(first):
            raise

        page = locator.page
        toast = await dismiss_pointer_blockers(page)
        if is_duplicate_deal_toast(toast):
            raise PanicError(
                f"PlatCore: сделка/реквизиты уже заняты — {toast[:240]}"
            ) from first

        await locator.scroll_into_view_if_needed()
        await random_pause(0.15, 0.3)
        try:
            await locator.click(timeout=click_timeout_ms)
            return
        except Exception as second:
            toast2 = await dismiss_pointer_blockers(page)
            if is_duplicate_deal_toast(toast2):
                raise PanicError(
                    f"PlatCore: сделка/реквизиты уже заняты — {toast2[:240]}"
                ) from second
            # Короткий force только после dismiss — иначе Playwright крутит retry вечно.
            await locator.click(timeout=3_000, force=True)
