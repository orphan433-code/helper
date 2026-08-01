"""Управление сессией Playwright: запуск, закрытие, cleanup вкладок."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from logkit import debug, info, warn

ROOT = Path(__file__).resolve().parent

_lock = threading.Lock()
_registered: BrowserSession | None = None


@dataclass
class BrowserSession:
    playwright: Playwright
    context: BrowserContext
    profile: Path

    @staticmethod
    def get_registered() -> BrowserSession | None:
        with _lock:
            return _registered

    @staticmethod
    def register(session: BrowserSession | None) -> None:
        global _registered
        with _lock:
            _registered = session

    @staticmethod
    def clear_registered() -> None:
        BrowserSession.register(None)


async def _apply_page_zoom(page: Page, zoom: float) -> None:
    if zoom == 1.0:
        return
    try:
        await page.evaluate(
            "(z) => { document.documentElement.style.zoom = String(z); }",
            zoom,
        )
    except Exception:
        pass


async def launch_browser(
    cfg: dict,
    *,
    headless: bool | None = None,
) -> BrowserSession:
    """Запуск persistent Chromium с профилем из config.

    headless=None — взять из config.yaml;
    для входа всегда передавай headless=False, иначе окна не будет видно.
    """
    # Старый сеанс мог остаться после ошибки/стопа — сначала чистый старт.
    await close_before_new_run()
    browser_cfg = cfg["browser"]
    profile = (ROOT / browser_cfg["user_data_dir"]).resolve()
    zoom = float(browser_cfg.get("page_zoom", 1.0) or 1.0)
    headless_flag = (
        bool(browser_cfg.get("headless", False))
        if headless is None
        else bool(headless)
    )
    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless_flag,
        viewport={"width": 1400, "height": 900},
        locale="ru-RU",
        args=["--disable-blink-features=AutomationControlled"],
    )
    if zoom != 1.0:
        await context.add_init_script(
            f"() => {{ document.documentElement.style.zoom = {zoom!r}; }}"
        )
        for page in context.pages:
            await _apply_page_zoom(page, zoom)
        debug(f"Масштаб вкладок: {zoom:g} ({zoom * 100:.0f}%)")
    session = BrowserSession(
        playwright=playwright, context=context, profile=profile
    )
    # Регистрируем сразу — stop/ошибка смогут закрыть браузер извне.
    BrowserSession.register(session)
    return session


async def close_session(
    session: BrowserSession | None,
    *,
    reason: str = "",
) -> None:
    """Закрыть браузер и остановить Playwright."""
    if session is None:
        return
    suffix = f" ({reason})" if reason else ""
    try:
        await session.context.close()
    except Exception as exc:
        warn(f"context.close: {exc}")
    try:
        await session.playwright.stop()
    except Exception as exc:
        warn(f"playwright.stop: {exc}")
    if BrowserSession.get_registered() is session:
        BrowserSession.clear_registered()
    info(f"Браузер закрыт{suffix}")


async def close_before_new_run() -> None:
    """Закрыть браузер от прошлого run (exit_after_run=false / отладка)."""
    prev = BrowserSession.get_registered()
    if prev is None:
        return
    info("Закрываем браузер предыдущего сеанса перед новым запуском")
    await close_session(prev, reason="новый запуск")


async def close_stale_tabs(
    context: BrowserContext,
    keep: Iterable[Page | None],
) -> int:
    """Закрыть вкладки, не входящие в keep (лишние списки после ошибок)."""
    keep_set = {
        page for page in keep if page is not None and not page.is_closed()
    }
    closed = 0
    for page in list(context.pages):
        if page in keep_set or page.is_closed():
            continue
        try:
            await page.close()
            closed += 1
        except Exception as exc:
            warn(f"Не удалось закрыть вкладку: {exc}")
    if closed:
        debug(f"Закрыто лишних вкладок: {closed}")
    return closed


def should_close_after_run(
    *,
    exit_after_run: bool,
    stopped: bool,
    cancelled: bool,
    error: bool = False,
) -> bool:
    """Закрывать браузер: всегда при стопе/отмене/ошибке; иначе по exit_after_run."""
    if stopped or cancelled or error:
        return True
    return exit_after_run


async def force_close_browser(*, reason: str = "принудительная остановка") -> None:
    """Закрыть активный браузер, если он ещё зарегистрирован."""
    prev = BrowserSession.get_registered()
    if prev is None:
        return
    await close_session(prev, reason=reason)
