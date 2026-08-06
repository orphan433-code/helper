"""Лёгкая хуманизация bank flow: jitter тапов, паузы, интервал ввода."""

from __future__ import annotations

import random
import time

from core.config import bank_settings


def enabled(cfg: dict | None = None) -> bool:
    return bool(bank_settings(cfg).get("bank_humanize", True))


def tap_xy(x: float, y: float, cfg: dict | None = None) -> tuple[int, int]:
    settings = bank_settings(cfg)
    if not enabled(settings):
        return int(round(x)), int(round(y))
    spread = int(settings.get("tap_jitter_px", 4))
    if spread <= 0:
        return int(round(x)), int(round(y))
    return (
        int(round(x + random.randint(-spread, spread))),
        int(round(y + random.randint(-spread, spread))),
    )


def click_pause(cfg: dict | None = None) -> None:
    """Короткая случайная пауза перед тапом (как human_click в PlatCore)."""
    settings = bank_settings(cfg)
    if not enabled(settings):
        return
    lo = float(settings.get("bank_click_pause_min_sec", 0.06))
    hi = float(settings.get("bank_click_pause_max_sec", 0.18))
    if hi <= 0:
        return
    time.sleep(random.uniform(min(lo, hi), max(lo, hi)))


def sleep_jitter(base: float, cfg: dict | None = None) -> None:
    """Фиксированная пауза ±bank_timing_jitter_pct."""
    if base <= 0:
        return
    settings = bank_settings(cfg)
    if not enabled(settings):
        time.sleep(base)
        return
    pct = float(settings.get("bank_timing_jitter_pct", 0.12))
    time.sleep(base * random.uniform(1.0 - pct, 1.0 + pct))


def key_interval(base: float, cfg: dict | None = None) -> float:
    """Интервал между символами с лёгким разбросом."""
    settings = bank_settings(cfg)
    if not enabled(settings) or base <= 0:
        return base
    pct = float(settings.get("form_key_interval_jitter_pct", 0.15))
    return base * random.uniform(1.0 - pct, 1.0 + pct)
