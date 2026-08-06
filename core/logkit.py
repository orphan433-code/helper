"""Краткий лог: консоль подробно, UI-журнал — только важное.

В журнал (UI):
  section / ok / warn / error
  info(..., ui=True) — редко, осознанно

info() по умолчанию только в консоль (без спама в журнал).
"""

from __future__ import annotations

import itertools
import re
import sys
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

LogSink = Callable[[dict[str, Any]], None]

_sink: LogSink | None = None
_id_seq = itertools.count(1)

_STDOUT_KEEP = re.compile(
    r"^\s*("
    r"\[OK\]|\[WARN\]|\[ERROR\]|\[ALERT\]|"
    r"!!! "
    r")"
)

_NOISE_SUBSTR = (
    "http request",
    "websocket",
    "devtools",
    "page.goto",
    "waiting for selector",
)


@lru_cache(maxsize=1)
def is_verbose() -> bool:
    try:
        from core.config import load_config

        cfg = load_config()
        return bool((cfg.get("logging") or {}).get("verbose", False))
    except Exception:
        return False


def reset_cache() -> None:
    is_verbose.cache_clear()


def set_ui_sink(sink: LogSink | None) -> None:
    """Подключить очередь UI (из app_web / app_gui)."""
    global _sink
    _sink = sink


def _guess_service(msg: str) -> str:
    m = (msg or "").casefold()
    if "редирект" in m or "redirect" in m:
        return "redirect"
    if "pending" in m or "dispute" in m or "approve" in m:
        return "pending"
    if "банк" in m or "перевод" in m or "bank" in m:
        return "bank"
    if "чек" in m or "completion" in m or "money sent" in m:
        return "completion"
    if "отмен" in m and "банк" in m:
        return "decline"
    if "platcore" in m or "accept" in m:
        return "platcore"
    if "adb" in m or "телефон" in m:
        return "device"
    if "отмен" in m or "cancel" in m or "alert" in m:
        return "watch"
    return "bot"


def _guess_status(level: str, msg: str) -> str:
    m = (msg or "").casefold()
    if level == "error":
        return "error"
    if level == "warning":
        return "warning"
    if "заверш" in m or "выполнен" in m or "принят" in m or "оплач" in m:
        return "ok"
    if "пропуск" in m or "skip" in m:
        return "skip"
    if "старт" in m or "запуск" in m or "цикл" in m:
        return "section"
    return "info"


def _guess_tags(level: str, msg: str, service: str) -> list[str]:
    tags = [service, level]
    m = (msg or "").casefold()
    if "пропуск" in m or "skip" in m:
        tags.append("skip")
    if "dispute" in m or "диспут" in m:
        tags.append("dispute")
    if "редирект" in m:
        tags.append("redirect")
    if "оплач" in m or "перевод выполнен" in m:
        tags.append("paid")
    if "accept" in m or "принят" in m:
        tags.append("accept")
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def make_event(
    message: str,
    *,
    level: str = "info",
    service: str = "",
    status: str = "",
    tags: list[str] | None = None,
    duration: str = "",
) -> dict[str, Any]:
    msg = str(message or "").strip()
    # В журнале допускаем многострочные итоги
    svc = (service or "").strip() or _guess_service(msg.replace("\n", " "))
    st = (status or "").strip() or _guess_status(level, msg)
    return {
        "id": str(next(_id_seq)),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level if level in ("info", "warning", "error") else "info",
        "service": svc,
        "message": msg,
        "duration": duration or "",
        "status": st,
        "tags": tags if tags is not None else _guess_tags(level, msg, svc),
    }


def emit_event(event: dict[str, Any]) -> None:
    sink = _sink
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        pass


def _out(msg: str, *, err: bool = False) -> None:
    stream = sys.__stderr__ if err else sys.__stdout__
    try:
        print(msg, file=stream, flush=True)
    except Exception:
        print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def _emit_line(
    console_line: str,
    message: str,
    *,
    level: str,
    service: str = "",
    status: str = "",
    tags: list[str] | None = None,
    err: bool = False,
    to_ui: bool = True,
) -> None:
    _out(console_line, err=err)
    if not to_ui:
        return
    emit_event(
        make_event(
            message,
            level=level,
            service=service,
            status=status,
            tags=tags,
        )
    )


def section(title: str) -> None:
    _emit_line(
        f"\n── {title} ──",
        title,
        level="info",
        service="bot",
        status="section",
        tags=["bot", "section"],
        to_ui=True,
    )


def ok(msg: str, *, service: str = "", ui: bool = True) -> None:
    _emit_line(
        f"[OK] {msg}",
        msg,
        level="info",
        service=service,
        status="ok",
        to_ui=ui,
    )


def warn(msg: str, *, service: str = "", ui: bool = True) -> None:
    _emit_line(
        f"[WARN] {msg}",
        msg,
        level="warning",
        service=service,
        status="warning",
        to_ui=ui,
    )


def error(msg: str, *, service: str = "", ui: bool = True) -> None:
    _emit_line(
        f"[ERROR] {msg}",
        msg,
        level="error",
        service=service,
        status="error",
        err=True,
        to_ui=ui,
    )


def info(msg: str, *, service: str = "", ui: bool = False) -> None:
    """По умолчанию только консоль. В журнал — info(..., ui=True)."""
    _emit_line(
        f"· {msg}",
        msg,
        level="info",
        service=service,
        to_ui=ui,
    )


def debug(msg: str) -> None:
    if is_verbose():
        _out(f"    {msg}")


def parse_stdout_chunk(text: str) -> list[dict[str, Any]]:
    """Сырой stdout → UI-события. Только OK/WARN/ERROR/ALERT (без [INFO] спама)."""
    events: list[dict[str, Any]] = []
    if not text:
        return events
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        low = line.casefold()
        if any(n in low for n in _NOISE_SUBSTR):
            continue
        if not _STDOUT_KEEP.match(line):
            continue

        level = "info"
        message = line
        if line.startswith("[ERROR]") or line.startswith("!!!"):
            level = "error"
            message = re.sub(r"^(\[ERROR\]|!!!)\s*", "", line).strip()
        elif line.startswith("[WARN]"):
            level = "warning"
            message = re.sub(r"^\[WARN\]\s*", "", line).strip()
        elif line.startswith("[OK]"):
            message = re.sub(r"^\[OK\]\s*", "", line).strip()
        elif line.startswith("[ALERT]"):
            level = "error"
            message = re.sub(r"^\[ALERT\]\s*", "", line).strip()

        if message:
            events.append(make_event(message, level=level))
    return events
