#!/usr/bin/env python3
"""Сохранение настроек из GUI в config.yaml."""

from __future__ import annotations

from config_loader import load_config, save_config


def apply_gui_settings(
    *,
    max_deals: int,
    min_amount: float | None = None,
    max_amount: float | None = None,
    allow_visa: bool | None = None,
    allow_mastercard: bool | None = None,
    max_empty_list_passes: int | None = None,
    from_pending: bool | None = None,
) -> None:
    cfg = load_config()
    pipe = dict(cfg.get("pipeline") or {})
    pipe["max_deals_per_run"] = max(1, min(50, int(max_deals)))
    if max_empty_list_passes is not None:
        pipe["max_empty_list_passes"] = max(1, min(20, int(max_empty_list_passes)))
    if from_pending is not None:
        pipe["from_pending"] = bool(from_pending)
    cfg["pipeline"] = pipe

    if (
        min_amount is not None
        or max_amount is not None
        or allow_visa is not None
        or allow_mastercard is not None
    ):
        val = dict(cfg.get("validation") or {})
        if min_amount is not None:
            val["min_amount"] = float(min_amount)
        if max_amount is not None:
            val["max_amount"] = float(max_amount)
        if allow_visa is not None:
            val["allow_visa"] = bool(allow_visa)
        if allow_mastercard is not None:
            val["allow_mastercard"] = bool(allow_mastercard)
        cfg["validation"] = val

    save_config(cfg)
