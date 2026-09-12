"""Запуск pipeline и login (консоль + GUI)."""

from __future__ import annotations

import asyncio
import sys

from core.browser_session import (
    BrowserSession,
    close_before_new_run,
    close_session,
    launch_browser,
    should_close_after_run,
)
from notify.cancel import (
    start_cancel_watch,
    stop_cancel_watch,
)
from core.config import load_config
from ui.hooks import enter_background, enter_foreground, set_automation_phase
from ui.job_control import JobStopped, begin_job, is_stopped, raise_if_stopped
from core.logkit import info, ok, section, warn
from platcore.pipeline import accept_deals_loop
from platcore.pending import claim_pending_deals_loop
from ui.prompts import wait_user_confirm
from core.validators import PanicError


async def run_login(service: str | None = None) -> None:
    begin_job()
    await close_before_new_run()
    cfg = load_config()
    from core.decline_hosts import DECLINE_SERVICE_EZE, DECLINE_SERVICE_URLS, normalize_decline_service
    from core.host_session import pay_out_url, write_cached_token

    key = normalize_decline_service(service)
    host = "EasySend" if key == DECLINE_SERVICE_EZE else "HZ"
    # Вход всегда в видимом окне — даже если в config headless=true.
    # page_zoom (0.4) только для DOM-списка; логин — 100%, API всё равно.
    session = await launch_browser(cfg, headless=False, for_login=True, service=key)
    dash_url = pay_out_url(key)

    section(f"Вход {host}")
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
            f"Войди в {host} в окне браузера и нажми «Я вошёл»"
        )
        raise_if_stopped()
        from platcore.api_client import capture_token_from_page, token_works

        token = await capture_token_from_page(page)
        base = DECLINE_SERVICE_URLS[key]
        if token and token_works(base, token):
            write_cached_token(token, service=key)
            from core.host_session import invalidate_session_status

            invalidate_session_status()
            ok(f"Сессия {host} сохранена")
        else:
            warn(
                f"Сессия {host}: токен не снялся. "
                "Проверь что кабинет открыт и жми вход ещё раз"
            )
    except JobStopped:
        info("Вход прерван")
    except asyncio.CancelledError:
        info("Вход прерван")
        raise
    finally:
        await close_session(session, reason="login")


async def run_pipeline(service: str | None = None) -> None:
    begin_job()
    cfg = load_config()
    pipe_cfg = cfg.get("pipeline") or {}
    comp_cfg = cfg.get("completion") or {}
    api_flow = cfg.get("api_flow") or {}
    api_enabled = bool(api_flow.get("enabled", False))
    from_pending = bool(pipe_cfg.get("from_pending", False))
    from core.decline_hosts import DECLINE_SERVICE_EZE, normalize_decline_service
    from core.deals_ui_local import pipeline_ui_service

    eze = (
        normalize_decline_service(service if service is not None else pipeline_ui_service())
        == DECLINE_SERVICE_EZE
    )
    if eze:
        from_pending = False
        api_enabled = True
    http_only = api_enabled and not from_pending
    exit_after_run = bool(pipe_cfg.get("exit_after_run", True))

    session = None
    await close_before_new_run()
    if not http_only:
        session = await launch_browser(cfg)

    section("Цикл tzk")
    if session is not None:
        info(f"Профиль: {session.profile.name}")
    else:
        info("API Accept: HTTP, как редирект — окно не открываем")
    if not exit_after_run and session is not None:
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
        if http_only:
            enter_foreground()
        else:
            enter_background()
        if from_pending:
            info("Режим: pending → Approve → банк → чеки (без Accept)")
            accepted_deals, page_by_order = await claim_pending_deals_loop(
                session.context, cfg
            )
        elif eze:
            from platcore.api_accept import accept_deals_loop_api

            info("Режим: e.hz Accept как HZ, пул GEL (отдельный Chrome)")
            accepted_deals, page_by_order = await accept_deals_loop_api(
                cfg, service="eze"
            )
        elif api_enabled:
            from platcore.api_accept import accept_deals_loop_api

            info(
                "Режим: API Accept"
                + (" + банк" if api_flow.get("run_bank") else "")
                + (
                    " + PUT upload/approve"
                    if api_flow.get("run_completion")
                    else ""
                )
            )
            accepted_deals, page_by_order = await accept_deals_loop_api(cfg)
        else:
            accepted_deals, page_by_order = await accept_deals_loop(
                session.context, cfg
            )

        run_completion = comp_cfg.get("enabled", True) and pipe_cfg.get(
            "run_completion_after_batch", True
        )
        if eze:
            from core.deals_ui_local import pipeline_ui_dry_stop

            if pipeline_ui_dry_stop():
                run_completion = False
                info("EZE: тест до SMS — чеки не грузим")
            elif run_completion:
                info("e.hz: чеки как HZ — overlay + банк")
            else:
                info("EZE: фаза чеков выключена")
        elif api_enabled and not api_flow.get("run_completion"):
            run_completion = False
            info("API-флоу: закрытие не трогаем — сверка руками")
        if run_completion and accepted_deals:
            raise_if_stopped()
            set_automation_phase("completion")
            enter_foreground()
            from completion.phase import run_completion_phase

            await run_completion_phase(
                session.context if session is not None else None,
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
        if session is None:
            pass
        elif should_close_after_run(
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
