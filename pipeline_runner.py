"""Запуск pipeline и login (консоль + GUI)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser_session import (
    BrowserSession,
    close_before_new_run,
    close_session,
    launch_browser,
    should_close_after_run,
)
from cancel_notify_watch import (
    start_cancel_watch,
    stop_cancel_watch,
)
from config_loader import load_config
from gui_hooks import enter_background, enter_foreground, set_automation_phase
from job_control import JobStopped, begin_job, is_stopped, raise_if_stopped
from logkit import info, ok, section, warn
from platcore_pipeline import accept_deals_loop
from user_prompts import wait_user_confirm
from validators import PanicError


async def run_login() -> None:
    begin_job()
    await close_before_new_run()
    cfg = load_config()
    # Вход всегда в видимом окне — даже если в config headless=true.
    session = await launch_browser(cfg, headless=False)
    dash_url = cfg["dashboard"]["monitor_url"]

    section("Вход в PlatCore")
    info(f"Профиль: {session.profile.name}")
    info("Открыто видимое окно браузера — войди в аккаунт")

    try:
        raise_if_stopped()
        page = (
            session.context.pages[0]
            if session.context.pages
            else await session.context.new_page()
        )
        await page.bring_to_front()
        await page.goto(dash_url, wait_until="domcontentloaded")
        await wait_user_confirm(
            "Войди в аккаунт в окне браузера и нажми «Я вошёл»"
        )
        raise_if_stopped()
        ok("Сессия PlatCore сохранена")
    except JobStopped:
        info("Вход прерван")
    except asyncio.CancelledError:
        info("Вход прерван")
        raise
    finally:
        await close_session(session, reason="login")


async def run_pipeline() -> None:
    begin_job()
    await close_before_new_run()
    cfg = load_config()
    session = await launch_browser(cfg)
    pipe_cfg = cfg.get("pipeline") or {}
    comp_cfg = cfg.get("completion") or {}
    exit_after_run = bool(pipe_cfg.get("exit_after_run", True))

    section("Цикл tzk")
    info(f"Профиль: {session.profile.name}")
    if not exit_after_run:
        info("При успехе браузер останется открытым (exit_after_run=false)")

    cancelled = False
    failed = False
    stopped_by_user = False
    bank_cfg = cfg.get("bank") or {}
    cancel_grace = float(bank_cfg.get("cancel_watch_grace_sec", 45))
    cancel_poll = float(bank_cfg.get("cancel_watch_poll_sec", 1.7))
    cancel_fee = float(bank_cfg.get("cancel_match_fee_rate", 0.018))
    start_cancel_watch(
        poll_sec=cancel_poll, verbose=True, fee_rate=cancel_fee
    )
    try:
        raise_if_stopped()
        set_automation_phase("bank")
        enter_background()
        accepted_deals, page_by_order = await accept_deals_loop(
            session.context, cfg
        )

        run_completion = comp_cfg.get("enabled", True) and pipe_cfg.get(
            "run_completion_after_batch", True
        )
        if run_completion and accepted_deals:
            raise_if_stopped()
            set_automation_phase("completion")
            enter_foreground()
            from completion_phase import run_completion_phase

            await run_completion_phase(
                session.context,
                cfg,
                accepted_deals=accepted_deals,
                page_by_order=page_by_order,
            )
        else:
            set_automation_phase("idle")

        if is_stopped():
            stopped_by_user = True
            info("Остановлено")
        else:
            ok("Цикл завершён")
    except JobStopped:
        stopped_by_user = True
        info("Остановлено пользователем")
    except asyncio.CancelledError:
        cancelled = True
        stopped_by_user = True
        info("Остановлено")
        raise
    except Exception:
        failed = True
        raise
    finally:
        # Хвост после последней сделки — успеть поймать «Otmena spisaniya».
        stop_cancel_watch(grace_sec=cancel_grace)
        set_automation_phase("idle")
        enter_foreground()
        # Стоп / отмена / ошибка — всегда гасим браузер (критично для headless).
        # Успех с exit_after_run=false — оставляем сессию для следующего запуска.
        if should_close_after_run(
            exit_after_run=exit_after_run,
            stopped=is_stopped() or stopped_by_user,
            cancelled=cancelled,
            error=failed,
        ):
            await close_session(session, reason="завершение")
        else:
            BrowserSession.register(session)
            info("Браузер оставлен открытым — закроется при следующем запуске")


def main() -> int:
    try:
        asyncio.run(run_pipeline())
        return 0
    except PanicError as exc:
        warn(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
