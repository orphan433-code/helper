"""Завершение сделки на PlatCore: чек + Money sent."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from human import HumanTiming, human_click
from logkit import debug, warn
from validators import PanicError

DROPZONE = '[data-testid="dropzone-files"]'
DROPZONE_LIST = '[data-testid="dropzone-files-list"]'
FILE_INPUT = f"{DROPZONE} input[type='file']"
_MODAL_SELECTOR = '[role="dialog"].chakra-modal__content, [role="dialog"].chakra-slide'
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
_DROPZONE_POLL_SEC = 0.5
_DROPZONE_WAIT_IMAGE_SEC = 30.0
_DROPZONE_WAIT_VIDEO_SEC = 600.0
_MONEY_SENT_READY_VIDEO_SEC = 480.0
_MONEY_SENT_READY_IMAGE_SEC = 60.0
# После клика Money sent: Confirmed / модалка ушла
_MONEY_SENT_RESULT_IMAGE_SEC = 90.0
_MONEY_SENT_RESULT_VIDEO_SEC = 600.0
_CONFIRMED_RE = re.compile(r"Confirmed", re.I)
_WAITING_APPROVE_RE = re.compile(r"Waiting\s+approve", re.I)
_VIDEO_REQUIRED_RE = re.compile(
    r"Please attach video with transaction|Deal payout video is require",
    re.I,
)
_VIDEO_REQUIRED_RECOVERY_ATTEMPTS = 2


class VideoRequiredPlatformBug(Exception):
    """Баг PlatCore: требует video после Money sent — нужен reload + Approve."""



async def _find_file_input(page: Page):
    loc = page.locator(FILE_INPUT)
    if await loc.count() > 0:
        return loc.first
    loc = page.locator('input[type="file"]')
    if await loc.count() > 0:
        return loc.first
    return None


async def _wait_money_sent_ready(
    page: Page,
    *,
    timeout_sec: float,
    wait_upload_idle: bool = False,
) -> None:
    """
    Ждём кликабельности Money sent.
    С видео — ещё и «тишину» в dropzone (нет upload/progress), 3 с стабильности.
    """
    btn = page.get_by_role("button", name="Money sent", exact=True)
    busy_re = re.compile(r"upload|загруз|progress|loading|\d+\s*%", re.I)
    deadline = time.monotonic() + timeout_sec
    last_log = 0.0
    stable_since: float | None = None
    stable_need = 3.0 if wait_upload_idle else 0.0

    if wait_upload_idle:
        await asyncio.sleep(2.0)

    while time.monotonic() < deadline:
        btn_ok = False
        try:
            if await btn.count() > 0:
                el = btn.first
                btn_ok = await el.is_visible() and await el.is_enabled()
        except Exception:
            btn_ok = False

        busy = False
        if wait_upload_idle:
            try:
                text = await page.locator(DROPZONE).inner_text(timeout=2000)
                busy = bool(busy_re.search(text or ""))
            except Exception:
                busy = False

        if btn_ok and not busy:
            if stable_need <= 0:
                debug("Money sent готова (enabled)")
                return
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_need:
                debug("Money sent готова, upload idle")
                return
        else:
            stable_since = None

        now = time.monotonic()
        if now - last_log >= 15.0:
            left = max(0.0, deadline - now)
            debug(f"Жду готовности Money sent / upload… ещё ~{left:.0f} с")
            last_log = now
        await asyncio.sleep(_DROPZONE_POLL_SEC)

    warn(
        f"Money sent / upload не готовы за {timeout_sec:g} с — "
        "пробую нажать всё равно"
    )


async def upload_proof_to_dropzone(
    page: Page,
    image_path: Path,
    *extra_paths: Path,
) -> bool:
    paths = [image_path, *extra_paths]
    resolved: list[str] = []
    for path in paths:
        if not path.is_file():
            raise PanicError(f"PlatCore: файл не найден: {path}")
        resolved.append(str(path.resolve()))

    has_video = any(Path(p).suffix.lower() in _VIDEO_EXTS for p in resolved)
    wait_list_sec = (
        _DROPZONE_WAIT_VIDEO_SEC if has_video else _DROPZONE_WAIT_IMAGE_SEC
    )
    ready_sec = (
        _MONEY_SENT_READY_VIDEO_SEC if has_video else _MONEY_SENT_READY_IMAGE_SEC
    )

    debug(f"PlatCore url: {page.url}")
    await page.wait_for_load_state("domcontentloaded")

    dropzone = page.locator(DROPZONE)
    try:
        await dropzone.wait_for(state="visible", timeout=60_000)
    except Exception as exc:
        raise PanicError(
            f"PlatCore: dropzone Attach document не найден за 60 с "
            f"(url={page.url!r})"
        ) from exc
    debug("Dropzone найден")

    file_input = await _find_file_input(page)
    if file_input is None:
        help_zone = page.locator('[data-testid="dropzone-help"]')
        if await help_zone.count():
            await help_zone.first.click()
            await asyncio.sleep(0.5)
        file_input = await _find_file_input(page)
    if file_input is None:
        raise PanicError(
            "PlatCore: input[type=file] не найден в dropzone Attach document"
        )

    files_list = page.locator(DROPZONE_LIST)
    before_count = await files_list.locator("*").count()
    names = ", ".join(Path(p).name for p in resolved)
    debug(
        f"Загрузка в dropzone: {names}"
        + (f" (видео, жду до {wait_list_sec:g} с)" if has_video else "")
    )
    await file_input.set_input_files(resolved)
    await asyncio.sleep(1.0)

    expect_delta = len(resolved)
    polls = max(1, int(wait_list_sec / _DROPZONE_POLL_SEC))
    appeared = False
    for i in range(polls):
        current = await files_list.locator("*").count()
        if current >= before_count + expect_delta:
            debug(f"Файлы в dropzone (+{current - before_count})")
            appeared = True
            break
        if current > before_count:
            await asyncio.sleep(_DROPZONE_POLL_SEC)
            continue
        if has_video and i > 0 and i % 30 == 0:
            debug(
                f"Видео ещё грузится в список… "
                f"{i * _DROPZONE_POLL_SEC:.0f}/{wait_list_sec:.0f} с"
            )
        await asyncio.sleep(_DROPZONE_POLL_SEC)

    if not appeared:
        warn(
            f"Dropzone: список не обновился за {wait_list_sec:g} с — продолжаем"
        )

    await _wait_money_sent_ready(
        page,
        timeout_sec=ready_sec,
        wait_upload_idle=has_video,
    )
    return has_video


async def _has_video_required_error(page: Page) -> bool:
    """Ошибка платформы: «Please attach video with transaction»."""
    try:
        loc = page.get_by_text(_VIDEO_REQUIRED_RE)
        n = await loc.count()
        for i in range(min(n, 5)):
            el = loc.nth(i)
            if await el.is_visible():
                return True
    except Exception:
        pass
    try:
        dialogs = page.locator(_MODAL_SELECTOR)
        n = await dialogs.count()
        for i in range(n):
            d = dialogs.nth(i)
            if not await d.is_visible():
                continue
            text = (await d.inner_text(timeout=1500)) or ""
            if _VIDEO_REQUIRED_RE.search(text):
                return True
    except Exception:
        pass
    return False


async def _recover_after_video_required_bug(
    page: Page,
    *,
    timing: HumanTiming,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Reload → Approve → снова модалка с dropzone (баг платформы)."""
    msg = "PlatCore bug: Please attach video — reload + Approve…"
    warn(msg)
    if on_progress is not None:
        on_progress(msg)
    await page.reload(wait_until="domcontentloaded")
    await asyncio.sleep(1.0)
    await ensure_completion_deal_ready(page, timing=timing)
    debug("После reload+Approve: dropzone снова готов")


async def _confirmed_modal(page: Page):
    """Модалка Confirmed / Waiting approve после Money sent."""
    dialogs = page.locator(_MODAL_SELECTOR)
    n = await dialogs.count()
    for i in range(n):
        d = dialogs.nth(i)
        try:
            if not await d.is_visible():
                continue
            text = (await d.inner_text(timeout=1500)) or ""
        except Exception:
            continue
        if _CONFIRMED_RE.search(text) or _WAITING_APPROVE_RE.search(text):
            return d
    return None


async def _money_sent_ui_gone(page: Page) -> bool:
    """Модалка перевода пропала: нет Money sent и нет dropzone."""
    try:
        ms = page.get_by_role("button", name="Money sent", exact=True)
        if await ms.count() > 0 and await ms.first.is_visible():
            return False
    except Exception:
        pass
    try:
        dz = page.locator(DROPZONE)
        if await dz.count() > 0 and await dz.first.is_visible():
            return False
    except Exception:
        pass
    return True


async def _wait_money_sent_result(
    page: Page,
    *,
    timeout_sec: float,
    timing: HumanTiming,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """
    Успех после клика — одно из двух (и скрин, и видео):
      1) модалка Confirmed / Waiting approve (+ Ok)
      2) модалка с Money sent / dropzone совсем пропала
    """
    deadline = time.monotonic() + timeout_sec
    last_log = 0.0
    gone_since: float | None = None
    gone_need = 1.2

    while time.monotonic() < deadline:
        if await _has_video_required_error(page):
            raise VideoRequiredPlatformBug(
                "PlatCore: Please attach video with transaction "
                "(баг платформы)"
            )

        confirmed = await _confirmed_modal(page)
        if confirmed is not None:
            debug("Money sent → Confirmed / Waiting approve")
            ok_btn = confirmed.get_by_role("button", name="Ok", exact=True)
            try:
                if await ok_btn.count() > 0 and await ok_btn.first.is_visible():
                    await human_click(ok_btn.first, timing=timing)
                    debug("Confirmed: нажал Ok")
            except Exception as exc:
                warn(f"Confirmed Ok не нажат: {exc}")
            return "confirmed"

        if await _money_sent_ui_gone(page):
            if gone_since is None:
                gone_since = time.monotonic()
            elif time.monotonic() - gone_since >= gone_need:
                debug("Money sent → модалка пропала")
                return "gone"
        else:
            gone_since = None

        now = time.monotonic()
        if now - last_log >= 15.0:
            left = max(0.0, deadline - now)
            msg = f"Жду подтверждение отправки… ещё ~{left:.0f} с"
            debug(msg)
            if on_progress is not None:
                on_progress(msg)
            last_log = now
        await asyncio.sleep(_DROPZONE_POLL_SEC)

    raise PanicError(
        f"PlatCore: после Money sent нет Confirmed и модалка не закрылась "
        f"за {timeout_sec:g} с (отправка ещё висит?)"
    )


async def click_money_sent(
    page: Page,
    *,
    timing: HumanTiming,
    fake: bool = False,
    has_video: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> str | None:
    """
    Клик Money sent + ожидание реального результата (Confirmed или модалка ушла).
    Общее для скрина и видео; у видео длиннее timeout.
    """
    await page.wait_for_load_state("domcontentloaded")
    btn = page.get_by_role("button", name="Money sent", exact=True)
    try:
        await btn.first.wait_for(state="visible", timeout=30_000)
    except Exception as exc:
        raise PanicError(
            "PlatCore: кнопка Money sent не появилась за 30 с"
        ) from exc
    if fake:
        debug("DRY-RUN: Money sent не нажат")
        return None
    await human_click(btn.first, timing=timing)
    result_sec = (
        _MONEY_SENT_RESULT_VIDEO_SEC if has_video else _MONEY_SENT_RESULT_IMAGE_SEC
    )
    wait_msg = (
        f"Money sent нажат — жду Confirmed / закрытие модалки "
        f"(до {result_sec:g} с"
        + (", видео" if has_video else "")
        + ")"
    )
    debug(wait_msg)
    if on_progress is not None:
        on_progress(
            "Жду подтверждение отправки (Confirmed или закрытие модалки)…"
        )
    return await _wait_money_sent_result(
        page,
        timeout_sec=result_sec,
        timing=timing,
        on_progress=on_progress,
    )


async def _has_completion_dropzone(page: Page) -> bool:
    try:
        dropzone = page.locator(DROPZONE)
        money_sent = page.get_by_role("button", name="Money sent", exact=True)
        if await dropzone.count() == 0 or await money_sent.count() == 0:
            return False
        return await dropzone.first.is_visible() and await money_sent.first.is_visible()
    except Exception:
        return False


async def _find_order_info_approve_button(page: Page):
    """Кнопка Approve в боковой панели Order info (после reopen по dealId)."""
    dialog = page.locator(_MODAL_SELECTOR).filter(
        has=page.get_by_text(re.compile(r"Order info", re.I))
    )
    if await dialog.count() > 0:
        btn = dialog.first.get_by_role("button", name="Approve", exact=True)
        if await btn.count() > 0:
            return btn.first

    btn = page.get_by_role("button", name="Approve", exact=True)
    if await btn.count() > 0:
        return btn.first
    return None


async def ensure_completion_deal_ready(page: Page, *, timing: HumanTiming) -> None:
    """
    После reopen по URL часто открывается Order info (Approve/Decline),
    а не модалка с dropzone. Кликаем Approve → ждём Attach document.
    """
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(450)

    if await _has_completion_dropzone(page):
        debug("Dropzone + Money sent уже на экране")
        return

    approve = await _find_order_info_approve_button(page)
    if approve is not None:
        try:
            if await approve.is_visible():
                debug("Order info → Approve")
                await human_click(approve, timing=timing)
                await asyncio.sleep(0.7)
        except Exception as exc:
            raise PanicError(f"PlatCore: не удалось нажать Approve: {exc}") from exc
    elif not await _has_completion_dropzone(page):
        raise PanicError(
            "PlatCore: нет Approve в Order info и нет dropzone "
            f"(url={page.url!r})"
        )

    if await _has_completion_dropzone(page):
        debug("Модалка с dropzone открыта")
        return

    from platcore_card import wait_for_post_accept_deal_card

    try:
        await wait_for_post_accept_deal_card(page, verbose=False)
    except PanicError:
        if not await _has_completion_dropzone(page):
            raise

    try:
        await page.locator(DROPZONE).first.wait_for(state="visible", timeout=60_000)
        await page.get_by_role("button", name="Money sent", exact=True).first.wait_for(
            state="visible",
            timeout=30_000,
        )
    except Exception as exc:
        raise PanicError(
            "PlatCore: dropzone / Money sent не появились после Approve"
        ) from exc

    debug("Attach document + Money sent готовы")


async def ensure_dropzone_on_page(page: Page) -> None:
    """Вкладка уже на post-accept модалке — только проверяем dropzone."""
    if page.is_closed():
        raise PanicError("PlatCore: вкладка сделки закрыта")
    await page.wait_for_load_state("domcontentloaded")
    dropzone = page.locator(DROPZONE)
    try:
        await dropzone.first.wait_for(state="visible", timeout=15_000)
    except Exception as exc:
        raise PanicError(
            f"PlatCore: dropzone не виден на открытой вкладке (url={page.url!r})"
        ) from exc
    btn = page.get_by_role("button", name="Money sent", exact=True)
    await btn.first.wait_for(state="visible", timeout=15_000)


async def open_deal_page(
    context: BrowserContext,
    platcore_url: str,
    *,
    reuse_page: Page | None = None,
    timing: HumanTiming,
    wait_for_card: bool = True,
) -> Page:
    if reuse_page is not None and not reuse_page.is_closed():
        page = reuse_page
        if page.url != platcore_url:
            await page.goto(platcore_url, wait_until="domcontentloaded")
    else:
        page = await context.new_page()
        await page.goto(platcore_url, wait_until="domcontentloaded")

    if wait_for_card:
        await ensure_completion_deal_ready(page, timing=timing)

    return page


async def complete_deal_on_platcore(
    page: Page,
    proof_path: Path,
    *,
    timing: HumanTiming,
    fake_money_sent: bool = False,
    deal_index: int | None = None,
    account_digits: str = "",
    video_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> str | None:
    if page.is_closed():
        raise PanicError("PlatCore: вкладка сделки закрыта — загрузка невозможна")

    prefix = f"#{deal_index} " if deal_index else ""
    card_hint = f"*{account_digits[-4:]}" if len(account_digits) >= 4 else ""
    debug(f"{prefix}PlatCore Money sent {card_hint}")

    extras: list[Path] = []
    if video_path is not None:
        extras.append(video_path)

    last_exc: BaseException | None = None
    for attempt in range(1, _VIDEO_REQUIRED_RECOVERY_ATTEMPTS + 1):
        try:
            has_video = await upload_proof_to_dropzone(page, proof_path, *extras)
            return await click_money_sent(
                page,
                timing=timing,
                fake=fake_money_sent,
                has_video=has_video,
                on_progress=on_progress,
            )
        except VideoRequiredPlatformBug as exc:
            last_exc = exc
            warn(
                f"{prefix}баг «attach video» "
                f"(попытка {attempt}/{_VIDEO_REQUIRED_RECOVERY_ATTEMPTS})"
            )
            if attempt >= _VIDEO_REQUIRED_RECOVERY_ATTEMPTS:
                break
            await _recover_after_video_required_bug(
                page, timing=timing, on_progress=on_progress
            )

    raise PanicError(
        f"{prefix}PlatCore: после reload+Approve снова "
        f"«Please attach video» — {last_exc}"
    )
