"""Краткий лог: только важное; детали — при logging.verbose: true."""

from __future__ import annotations

import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def is_verbose() -> bool:
    try:
        from config_loader import load_config

        cfg = load_config()
        return bool((cfg.get("logging") or {}).get("verbose", False))
    except Exception:
        return False


def reset_cache() -> None:
    is_verbose.cache_clear()


def _out(msg: str, *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def section(title: str) -> None:
    _out(f"\n── {title} ──")


def ok(msg: str) -> None:
    _out(f"[OK] {msg}")


def warn(msg: str) -> None:
    _out(f"[WARN] {msg}")


def error(msg: str) -> None:
    _out(f"[ERROR] {msg}", err=True)


def info(msg: str) -> None:
    _out(f"· {msg}")


def debug(msg: str) -> None:
    if is_verbose():
        _out(f"    {msg}")
