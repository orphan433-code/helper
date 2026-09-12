"""Управление сессией Playwright: запуск, закрытие, cleanup вкладок."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from core.logkit import debug, info, warn

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
# Логин: 100% масштаб, окно как обычный Chrome (~16:10 ноутбук).
_LOGIN_WINDOW = {"width": 1440, "height": 900}
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


async def _fit_os_window(
    context: BrowserContext,
    *,
    width: int,
    height: int,
) -> None:
    """Профиль Chrome помнит крошечное окно — вернуть нормальный размер."""
    for page in context.pages:
        try:
            if page.is_closed():
                continue
            cdp = await context.new_cdp_session(page)
            win = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": win["windowId"],
                    "bounds": {
                        "width": width,
                        "height": height,
                        "windowState": "normal",
                    },
                },
            )
        except Exception:
            continue
        break


async def launch_browser(
    cfg: dict,
    *,
    headless: bool | None = None,
    zoom: float | None = None,
    window_size: dict[str, int] | None = None,
    for_login: bool = False,
    service: str | None = None,
) -> BrowserSession:
    """Запуск persistent Chromium с профилем из config.

    headless=None — взять из config.yaml;
    для входа всегда передавай headless=False, иначе окна не будет видно.
    for_login=True — масштаб 100% и окно 1440×900, игнор page_zoom.
    service=eze — отдельный профиль EasySend, не HZ.
    """
    from core.host_session import profile_dir

    # Старый сеанс мог остаться после ошибки/стопа — сначала чистый старт.
    await close_before_new_run()
    browser_cfg = cfg["browser"]
    profile = profile_dir(cfg, service=service)
    if for_login:
        zoom = 1.0
        window_size = window_size or _LOGIN_WINDOW
    if zoom is None:
        zoom = float(browser_cfg.get("page_zoom", 1.0) or 1.0)
    else:
        zoom = float(zoom or 1.0)
    size = window_size or _VIEWPORT
    width = int(size.get("width") or _VIEWPORT["width"])
    height = int(size.get("height") or _VIEWPORT["height"])
    headless_flag = (
        bool(browser_cfg.get("headless", False))
        if headless is None
        else bool(headless)
    )
    playwright = await async_playwright().start()
    args = ["--disable-blink-features=AutomationControlled"]
    if not headless_flag:
        args.append(f"--window-size={width},{height}")
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless_flag,
        viewport={"width": width, "height": height},
        locale="ru-RU",
        args=args,
    )
    if for_login and not headless_flag:
        await _fit_os_window(context, width=width, height=height)
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
