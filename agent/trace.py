"""Логи AI-агента: терминал + UI (потом выключить agent.verbose)."""

from __future__ import annotations

import sys
from typing import Callable

from agent.config import agent_settings

_trace_sinks: list[Callable[[str], None]] = []


def agent_verbose() -> bool:
    return bool(agent_settings().get("verbose", True))


def register_trace_sink(cb: Callable[[str], None]) -> None:
    if cb not in _trace_sinks:
        _trace_sinks.append(cb)


def agent_trace(msg: str) -> None:
    if not agent_verbose():
        return
    line = str(msg or "").strip()
    if not line:
        return
    tagged = f"[AGENT] {line}"
    for sink in _trace_sinks:
        try:
            sink(line)
        except Exception:
            pass
    try:
        print(tagged, flush=True)
    except Exception:
        pass
    try:
        sys.__stdout__.write(tagged + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass
