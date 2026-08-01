#!/usr/bin/env python3
"""Tzk в браузере: http://127.0.0.1:8765

Не трогает pywebview (app_web.py). Отдельный FastAPI-сервер + bridge.js.
Движок (TzkApi) можно выключить / включить / перезапустить из UI —
страница при этом остаётся доступной.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import traceback
import time
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, Response
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[misc, assignment]
    WebSocket = Any  # type: ignore[misc, assignment]
    WebSocketDisconnect = Exception  # type: ignore[misc, assignment]
    HTMLResponse = Any  # type: ignore[misc, assignment]
    Response = Any  # type: ignore[misc, assignment]

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WEB_UI = ROOT / "web_ui"
BRIDGE_JS = WEB_UI / "bridge.js"
INDEX_HTML = WEB_UI / "index.html"
FAVICON_SVG = WEB_UI / "favicon.svg"

HOST = "127.0.0.1"
PORT = 8765


class EventHub:
    """Рассылка UI-событий подключённым WebSocket-клиентам."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subscribers)
        loop = self._loop
        if loop is None or not subs:
            return

        def _push() -> None:
            for q in subs:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except Exception:
                        pass
                    try:
                        q.put_nowait(event)
                    except Exception:
                        pass

        try:
            loop.call_soon_threadsafe(_push)
        except RuntimeError:
            pass


class BrowserTzkApi:
    """Обёртка над TzkApi: пуш в WebSocket вместо evaluate_js."""

    def __init__(self, hub: EventHub) -> None:
        from app_web import TzkApi

        self._hub = hub
        self._api = TzkApi()
        self._api._notify_ui = self._notify_ui  # type: ignore[method-assign]
        self._api._focus_window = lambda: None  # type: ignore[method-assign]
        self._api._minimize_window = lambda: None  # type: ignore[method-assign]

    def _notify_ui(self, script: str) -> None:
        if script:
            self._hub.broadcast({"type": "eval", "script": script})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._api, name)


class EngineController:
    def __init__(self, hub: EventHub) -> None:
        self.hub = hub
        self._lock = threading.Lock()
        self._engine_on = True
        self._restarting = False
        self.api = BrowserTzkApi(hub)

    @property
    def engine_on(self) -> bool:
        return self._engine_on

    @property
    def restarting(self) -> bool:
        return self._restarting

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "engine_on": self._engine_on,
            "restarting": self._restarting,
            "job_running": bool(getattr(self.api, "_running", False)),
        }

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._engine_on = True
        self.hub.broadcast({"type": "engine", "engine_on": True})
        return {"ok": True, "engine_on": True}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._engine_on = False
        try:
            self.api.stop_job()
        except Exception:
            pass
        try:
            from cancel_notify_watch import stop_cancel_watch_now

            stop_cancel_watch_now()
        except Exception:
            pass
        self.hub.broadcast({"type": "engine", "engine_on": False})
        return {"ok": True, "engine_on": False}

    def restart(self) -> dict[str, Any]:
        with self._lock:
            if self._restarting:
                return {"ok": False, "error": "Уже перезапускается"}
            self._restarting = True
        try:
            try:
                self.api.stop_job()
            except Exception:
                pass
            # Дать worker-потоку чуть времени на выход
            worker = getattr(self.api, "_worker", None)
            if worker is not None and worker.is_alive():
                worker.join(timeout=2.0)
            self.api = BrowserTzkApi(self.hub)
            self._engine_on = True
            self.hub.broadcast({"type": "engine", "engine_on": True})
            self.hub.broadcast(
                {
                    "type": "eval",
                    "script": 'setStatus("Движок перезапущен", "idle");'
                    'if (typeof hideRecoveryPrompt==="function") hideRecoveryPrompt();'
                    'if (typeof clearPipelineProgress==="function") clearPipelineProgress();'
                    'if (typeof clearReceiptProgress==="function") clearReceiptProgress();'
                    'if (typeof clearDeclineResult==="function") clearDeclineResult();'
                    'if (typeof clearCancelAlerts==="function") clearCancelAlerts();',
                }
            )
            return {"ok": True, "engine_on": True, "restarted": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with self._lock:
                self._restarting = False

    def shutdown(self) -> dict[str, Any]:
        """Остановить задачу и полностью выключить HTTP-сервер."""
        try:
            self.stop()
        except Exception:
            pass
        self.hub.broadcast(
            {
                "type": "eval",
                "script": 'if (typeof setStatus==="function") '
                'setStatus("Выключение…", "idle");',
            }
        )

        def _exit() -> None:
            time.sleep(0.35)
            os._exit(0)

        threading.Thread(target=_exit, name="tzk-shutdown", daemon=True).start()
        return {"ok": True, "shutting_down": True}


def _inject_bridge(html: str) -> str:
    tag = '<script src="/bridge.js"></script>\n'
    if "bridge.js" in html:
        return html
    if "<script>" in html:
        return html.replace("<script>", tag + "  <script>", 1)
    return html.replace("</body>", tag + "</body>")


def create_app() -> Any:
    if FastAPI is None:
        raise SystemExit(
            "Нужны fastapi и uvicorn:\n"
            "  pip install fastapi uvicorn\n"
        )

    hub = EventHub()
    engine = EngineController(hub)
    app = FastAPI(title="Tzk Browser", docs_url=None, redoc_url=None)

    READ_ALWAYS = {
        "get_state",
        "poll_logs",
        "check_adb",
        "save_settings",
        "open_screens_folder",
        "open_videos_folder",
        "get_update_status",
        "apply_app_update",
    }

    @app.on_event("startup")
    async def _startup() -> None:
        hub.set_loop(asyncio.get_running_loop())

    @app.get("/")
    async def index() -> HTMLResponse:
        if not INDEX_HTML.is_file():
            return HTMLResponse("Не найден web_ui/index.html", status_code=500)
        html = _inject_bridge(INDEX_HTML.read_text(encoding="utf-8"))
        html = html.replace(
            "<title>Tzk — PlatCore</title>",
            "<title>Tzk Browser — PlatCore</title>",
            1,
        )
        return HTMLResponse(html)

    @app.get("/bridge.js")
    async def bridge() -> Response:
        if not BRIDGE_JS.is_file():
            return Response("// missing bridge.js", media_type="application/javascript", status_code=404)
        return Response(
            BRIDGE_JS.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @app.get("/favicon.svg")
    @app.get("/favicon.ico")
    async def favicon() -> Response:
        if not FAVICON_SVG.is_file():
            return Response(status_code=404)
        return Response(
            FAVICON_SVG.read_text(encoding="utf-8"),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/server/status")
    async def server_status() -> dict[str, Any]:
        return engine.status()

    @app.post("/api/server/start")
    async def server_start() -> dict[str, Any]:
        return await asyncio.to_thread(engine.start)

    @app.post("/api/server/stop")
    async def server_stop() -> dict[str, Any]:
        return await asyncio.to_thread(engine.stop)

    @app.post("/api/server/restart")
    async def server_restart() -> dict[str, Any]:
        return await asyncio.to_thread(engine.restart)

    @app.post("/api/server/shutdown")
    async def server_shutdown() -> dict[str, Any]:
        return await asyncio.to_thread(engine.shutdown)

    @app.get("/api/get_state")
    async def get_state() -> dict[str, Any]:
        state = await asyncio.to_thread(engine.api.get_state)
        state["engine_on"] = engine.engine_on
        state["browser_mode"] = True
        if not engine.engine_on:
            state["status"] = "Движок выключен"
            state["running"] = False
        return state

    @app.get("/api/poll_logs")
    async def poll_logs() -> dict[str, Any]:
        text = await asyncio.to_thread(engine.api.poll_logs)
        return {"ok": True, "text": text or ""}

    def _guard(method: str) -> dict[str, Any] | None:
        if engine.restarting:
            return {"ok": False, "error": "Движок перезапускается, подожди…"}
        if not engine.engine_on and method not in READ_ALWAYS:
            return {
                "ok": False,
                "error": "Движок выключен. Нажми «Включить» вверху страницы.",
            }
        return None

    async def _call(method: str, **kwargs: Any) -> Any:
        blocked = _guard(method)
        if blocked is not None:
            return blocked
        fn = getattr(engine.api, method, None)
        if fn is None or not callable(fn):
            return {"ok": False, "error": f"Нет метода: {method}"}
        try:
            return await asyncio.to_thread(lambda: fn(**kwargs))
        except TypeError:
            # positional-only quirks — try without names for empty
            try:
                return await asyncio.to_thread(fn)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        except Exception as exc:
            traceback.print_exc()
            return {"ok": False, "error": str(exc)}

    @app.post("/api/save_settings")
    async def save_settings(body: dict[str, Any]) -> Any:
        return await _call(
            "save_settings",
            max_deals=body.get("max_deals"),
            min_amount=body.get("min_amount", ""),
            max_amount=body.get("max_amount", ""),
            allow_visa=body.get("allow_visa", True),
            allow_mastercard=body.get("allow_mastercard", False),
            max_empty_list_passes=body.get("max_empty_list_passes"),
        )

    @app.post("/api/start_login")
    async def start_login() -> Any:
        return await _call("start_login")

    @app.post("/api/start_pipeline")
    async def start_pipeline(body: dict[str, Any]) -> Any:
        return await _call(
            "start_pipeline",
            max_deals=body.get("max_deals"),
            min_amount=body.get("min_amount", ""),
            max_amount=body.get("max_amount", ""),
            allow_visa=body.get("allow_visa", True),
            allow_mastercard=body.get("allow_mastercard", False),
            max_empty_list_passes=body.get("max_empty_list_passes"),
        )

    @app.post("/api/start_decline")
    async def start_decline(body: dict[str, Any] | None = None) -> Any:
        body = body or {}
        return await _call("start_decline", bank=body.get("bank", "tbc"))

    @app.post("/api/start_redirect")
    async def start_redirect(body: dict[str, Any]) -> Any:
        return await _call(
            "start_redirect",
            trader_ids=body.get("trader_ids"),
            max_per_run=body.get("max_per_run"),
            min_amount=body.get("min_amount"),
            max_amount=body.get("max_amount"),
            deal_status=body.get("deal_status"),
            skip_bog=body.get("skip_bog", False),
            visa_only=body.get("visa_only", False),
        )

    @app.post("/api/stop_job")
    async def stop_job() -> Any:
        return await _call("stop_job")

    @app.post("/api/confirm")
    async def confirm(body: dict[str, Any]) -> Any:
        return await _call("confirm", kind=body.get("kind", "receipts"))

    @app.post("/api/cancel_completion_deal")
    async def cancel_completion_deal(body: dict[str, Any]) -> Any:
        return await _call("cancel_completion_deal", order_id=body.get("order_id", ""))

    @app.post("/api/retry_completion_deal")
    async def retry_completion_deal(body: dict[str, Any]) -> Any:
        return await _call("retry_completion_deal", order_id=body.get("order_id", ""))

    @app.post("/api/rescan_completion_deal")
    async def rescan_completion_deal(body: dict[str, Any]) -> Any:
        return await _call("rescan_completion_deal", order_id=body.get("order_id", ""))

    @app.get("/api/preview_receipts")
    async def preview_receipts() -> Any:
        return await _call("preview_receipts")

    @app.post("/api/recovery_continue")
    async def recovery_continue() -> Any:
        return await _call("recovery_continue")

    @app.post("/api/recovery_retry")
    async def recovery_retry() -> Any:
        return await _call("recovery_retry")

    @app.post("/api/recovery_exit")
    async def recovery_exit() -> Any:
        return await _call("recovery_exit")

    @app.post("/api/open_screens_folder")
    async def open_screens_folder() -> Any:
        return await _call("open_screens_folder")

    @app.post("/api/open_videos_folder")
    async def open_videos_folder() -> Any:
        return await _call("open_videos_folder")

    @app.get("/api/check_adb")
    async def check_adb() -> Any:
        return await _call("check_adb")

    @app.get("/api/get_update_status")
    async def get_update_status() -> Any:
        return await _call("get_update_status")

    @app.post("/api/apply_app_update")
    async def apply_app_update() -> Any:
        return await _call("apply_app_update")

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        q = hub.subscribe()
        try:
            await websocket.send_json({"type": "engine", **engine.status()})
            while True:
                # Логи UI продолжает забирать через poll_logs — здесь только push-события.
                event = await q.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub.unsubscribe(q)

    # keep refs for tests / debugging
    app.state.engine = engine  # type: ignore[attr-defined]
    app.state.hub = hub  # type: ignore[attr-defined]
    return app


class _QuietAccessFilter:
    """Глушит частый polling в access-log (poll_logs / server status)."""

    _SKIP = ("/api/poll_logs", "/api/server/status")

    def filter(self, record: Any) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(path in msg for path in self._SKIP)


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        print(
            "Нужны fastapi и uvicorn:\n"
            "  pip install fastapi 'uvicorn[standard]'\n"
            f"({exc})",
            file=sys.stderr,
        )
        sys.exit(1)

    if FastAPI is None:
        print(
            "Нужны fastapi и uvicorn:\n"
            "  pip install fastapi 'uvicorn[standard]'",
            file=sys.stderr,
        )
        sys.exit(1)

    if not INDEX_HTML.is_file():
        print(f"Не найден UI: {INDEX_HTML}", file=sys.stderr)
        sys.exit(1)
    if not BRIDGE_JS.is_file():
        print(f"Не найден bridge: {BRIDGE_JS}", file=sys.stderr)
        sys.exit(1)

    logging.getLogger("uvicorn.access").addFilter(_QuietAccessFilter())  # type: ignore[arg-type]

    print(f"Tzk Browser → http://{HOST}:{PORT}")
    print("Pywebview (app_web.py) не затронут. Ctrl+C — остановить HTTP.")
    uvicorn.run(
        "app_browser:create_app",
        factory=True,
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
