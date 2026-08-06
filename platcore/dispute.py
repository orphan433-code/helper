"""PlatCore: I have a problem → dispute (отмена без чека)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import Page

from core.human import HumanTiming, human_click
from core.logkit import debug, warn
from core.validators import PanicError

DESCRIBE_INPUT = '[data-testid="describe-problem-input"]'
_DEFAULT_MESSAGE = (
    "Отменяем, не ушло. Если перевод не прошёл он пропадает из истории"
)


@dataclass(frozen=True)
class DisputeConfig:
    topic: str
    message: str
    fake_submit: bool


def parse_dispute_config(cfg: dict) -> DisputeConfig:
    comp = cfg.get("completion") or {}
    stage2 = cfg.get("stage2") or {}
    return DisputeConfig(
        topic=str(comp.get("dispute_topic", "Хук не дошел")).strip(),
        message=str(comp.get("dispute_message", _DEFAULT_MESSAGE)).strip(),
        fake_submit=bool(
            comp.get("fake_dispute", False) or stage2.get("fake_money_sent", False)
        ),
    )


async def _problem_form(page: Page):
    form = page.locator("form.chakra-stack").filter(
        has=page.locator(DESCRIBE_INPUT)
    )
    await form.first.wait_for(state="visible", timeout=30_000)
    return form.first


async def click_i_have_a_problem(page: Page, *, timing: HumanTiming) -> None:
    await page.wait_for_load_state("domcontentloaded")
    btn = page.get_by_role("button", name="I have a problem", exact=True)
    await btn.first.wait_for(state="visible", timeout=30_000)
    await human_click(btn.first, timing=timing)
    debug("PlatCore: I have a problem")


async def select_dispute_topic(page: Page, topic: str) -> None:
    form = await _problem_form(page)
    trigger = form.locator('[id^="popover-trigger-"]').first
    await trigger.wait_for(state="visible", timeout=10_000)
    await trigger.click()
    await asyncio.sleep(0.4)

    popover = page.locator('[id^="popover-content-"]')
    option = popover.get_by_text(topic, exact=True)
    try:
        await popover.first.wait_for(state="visible", timeout=5_000)
        await option.first.wait_for(state="visible", timeout=5_000)
        await option.first.click()
    except Exception:
        search = form.locator('[data-testid="undefined-search-input"]')
        if await search.count():
            await search.first.fill(topic)
            await asyncio.sleep(0.3)
        await option.first.wait_for(state="visible", timeout=10_000)
        await option.first.click()
    debug(f"PlatCore dispute topic: {topic!r}")


async def fill_dispute_description(page: Page, message: str) -> None:
    form = await _problem_form(page)
    textarea = form.locator(DESCRIBE_INPUT)
    await textarea.wait_for(state="visible", timeout=10_000)
    await textarea.fill(message)
    debug(f"PlatCore dispute text: {message!r}")


async def click_dispute_continue(
    page: Page,
    *,
    timing: HumanTiming,
    fake: bool,
) -> None:
    footer = page.locator(".chakra-modal__footer").filter(
        has=page.get_by_role("button", name="Back", exact=True)
    )
    btn = footer.get_by_role("button", name="Continue", exact=True)
    await btn.wait_for(state="visible", timeout=15_000)
    if fake:
        debug("DRY-RUN: Continue (dispute) не нажат")
        return
    await human_click(btn, timing=timing)
    debug("PlatCore: Continue — dispute отправлен")


async def _wait_dispute_done(page: Page, *, timeout_sec: float = 60.0) -> None:
    """Форма describe / Money sent пропали — отмена принята."""
    deadline = time.monotonic() + timeout_sec
    gone_since: float | None = None
    while time.monotonic() < deadline:
        form_visible = False
        try:
            form = page.locator("form.chakra-stack").filter(
                has=page.locator(DESCRIBE_INPUT)
            )
            if await form.count() > 0 and await form.first.is_visible():
                form_visible = True
        except Exception:
            form_visible = False

        money_sent = False
        try:
            ms = page.get_by_role("button", name="Money sent", exact=True)
            if await ms.count() > 0 and await ms.first.is_visible():
                money_sent = True
        except Exception:
            money_sent = False

        if not form_visible and not money_sent:
            if gone_since is None:
                gone_since = time.monotonic()
            elif time.monotonic() - gone_since >= 1.0:
                debug("Dispute: модалка ушла")
                return
        else:
            gone_since = None

        await asyncio.sleep(0.4)

    warn(
        f"Dispute: UI не подтвердил закрытие за {timeout_sec:g} с — считаем отправленным"
    )


async def submit_dispute_without_proof(
    page: Page,
    dispute: DisputeConfig,
    *,
    timing: HumanTiming,
    deal_index: int | None = None,
) -> None:
    """
    Отмена сделки: I have a problem → topic → текст → Continue.
    Чек / видео не крепим.
    """
    if page.is_closed():
        raise PanicError("PlatCore: вкладка сделки закрыта — отмена невозможна")
    if not dispute.message:
        raise PanicError("PlatCore dispute: dispute_message пустой")
    if not dispute.topic:
        raise PanicError("PlatCore dispute: dispute_topic пустой")

    prefix = f"#{deal_index} " if deal_index else ""
    debug(f"{prefix}PlatCore dispute (без чека)…")

    await click_i_have_a_problem(page, timing=timing)
    await select_dispute_topic(page, dispute.topic)
    await fill_dispute_description(page, dispute.message)
    await click_dispute_continue(
        page, timing=timing, fake=dispute.fake_submit
    )
    if not dispute.fake_submit:
        await _wait_dispute_done(page)
