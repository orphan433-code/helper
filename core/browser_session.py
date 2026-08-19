"""Управление сессией Playwright: запуск, закрытие, cleanup вкладок."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from core.logkit import debug, info, warn

from core.paths import ROOT

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


_VIEWPORT = {"width": 1400, "height": 900}
_ZOOM_STYLE_JS = """
(z) => {
  if (!z || Math.abs(z - 1) < 1e-6) return;
  const apply = () => {
    const root = document.documentElement;
    const id = '__tzk_zoom';
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement('style');
      el.id = id;
      (document.head || root).appendChild(el);
    }
    const layoutH = Math.round(window.innerHeight / z);
    el.textContent = [
      'html { zoom: ' + z + ' !important; }',
      'html, body { overflow: hidden !important; }',
      ':root { --window-inner-height: ' + layoutH + 'px !important; }',
    ].join('\\n');
    root.style.setProperty('zoom', String(z), 'important');
    root.style.setProperty('--window-inner-height', layoutH + 'px', 'important');
  };
  apply();
  document.addEventListener('DOMContentLoaded', apply);
  if (!window.__tzk_zoom_hook) {
    window.__tzk_zoom_hook = true;
    new MutationObserver(apply).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style', 'class'],
    });
    window.addEventListener('resize', apply);
    window.setInterval(apply, 800);
  }
}
"""


def _zoom_init_script(zoom: float) -> str:
    return f"() => {{ ({_ZOOM_STYLE_JS})({zoom!r}); }}"


async def _apply_page_zoom(page: Page, zoom: float) -> None:
    """CSS zoom + компенсация --window-inner-height, чтобы таблица
    заполняла окно. Без CDP (он раздувает innerHeight и ломает скролл).
    """
    if zoom <= 0 or abs(zoom - 1.0) < 1e-6:
        return
    try:
        if page.is_closed():
            return
    except Exception:
        return
    try:
        await page.evaluate(_ZOOM_STYLE_JS, zoom)
    except Exception:
        pass


def _install_zoom_hooks(context: BrowserContext, zoom: float):
    if abs(zoom - 1.0) < 1e-6:
        return None

    async def _hook(page: Page) -> None:
        await _apply_page_zoom(page, zoom)

        def _reapply(*_args: object) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(_apply_page_zoom(page, zoom))

        page.on("load", _reapply)
        page.on("domcontentloaded", _reapply)

    def _on_page(page: Page) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(_hook(page))

    context.on("page", _on_page)
    return _hook


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
        viewport={"width": _VIEWPORT["width"], "height": _VIEWPORT["height"]},
        locale="ru-RU",
        args=["--disable-blink-features=AutomationControlled"],
    )
    if abs(zoom - 1.0) >= 1e-6:
        await context.add_init_script(_zoom_init_script(zoom))
        hook = _install_zoom_hooks(context, zoom)
        if hook is not None:
            for page in context.pages:
                await hook(page)
        info(f"Масштаб страницы: {zoom * 100:.0f}%")
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
