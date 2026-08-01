"""Управление окном GUI на время автоматизации (свернуть на сессию, не на каждую сделку)."""

from __future__ import annotations

import threading
from typing import Callable, Literal

AutomationPhase = Literal["bank", "completion", "idle"]

_lock = threading.Lock()
_gui_mode = False
_background_active = False
_phase: AutomationPhase = "idle"
_on_background: Callable[[], None] | None = None
_on_foreground: Callable[[], None] | None = None


def set_gui_mode(enabled: bool = True) -> None:
    global _gui_mode
    with _lock:
        _gui_mode = enabled


def is_gui_mode() -> bool:
    with _lock:
        return _gui_mode


def set_automation_phase(phase: AutomationPhase) -> None:
    global _phase
    with _lock:
        _phase = phase


def is_completion_phase() -> bool:
    with _lock:
        return _phase == "completion"


def is_bank_phase() -> bool:
    with _lock:
        return _phase == "bank"


def set_job_window_hooks(
    on_background: Callable[[], None] | None,
    on_foreground: Callable[[], None] | None,
) -> None:
    global _on_background, _on_foreground
    with _lock:
        _on_background = on_background
        _on_foreground = on_foreground


def clear_job_window_hooks() -> None:
    set_job_window_hooks(None, None)


def reset_window_session() -> None:
    """Сброс флага при старте worker (после прошлого сбоя)."""
    global _background_active, _phase
    with _lock:
        _background_active = False
        _phase = "idle"


def enter_background() -> None:
    """Свернуть окно на фазе банка — не трогать на этапе чеков (браузер)."""
    global _background_active
    with _lock:
        if not _gui_mode or _background_active or _phase == "completion":
            return
        _background_active = True
        hook = _on_background
    if hook is not None:
        try:
            hook()
        except Exception:
            pass


def enter_foreground() -> None:
    """Вернуть окно: конец этапа, ошибка, этап чеков."""
    global _background_active
    with _lock:
        if not _background_active:
            return
        _background_active = False
        hook = _on_foreground
    if hook is not None:
        try:
            hook()
        except Exception:
            pass


def notify_bank_handoff_start() -> None:
    enter_background()


def notify_bank_handoff_end() -> None:
    pass
