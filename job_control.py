"""Остановка pipeline / login из GUI."""

from __future__ import annotations

import threading

_stop = threading.Event()


class JobStopped(Exception):
    """Пользователь нажал «Стоп»."""


def begin_job() -> None:
    _stop.clear()


def request_stop() -> None:
    _stop.set()


def is_stopped() -> bool:
    return _stop.is_set()


def raise_if_stopped() -> None:
    if _stop.is_set():
        raise JobStopped("Остановлено пользователем")
