#!/usr/bin/env python3
"""Сохранение настроек из GUI."""

from __future__ import annotations

from core.config import load_config, save_config
from core.deals_ui_local import _patch_section, load_local
from core.decline_bins import (
    DECLINE_BIN_PREFIXES,
    DECLINE_DEFAULT_PER_RUN,
    clamp_decline_limit,
)
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES
from core.paths import ROOT

DECLINE_CONFIG = ROOT / "platcore-decline" / "config.yaml"
DECLINE_EXAMPLE = ROOT / "platcore-decline" / "config.example.yaml"


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

    # API Accept читает pipeline; api_flow.max_deals — legacy, держим в sync
    api_flow = dict(cfg.get("api_flow") or {})
    api_flow["max_deals"] = pipe["max_deals_per_run"]
    cfg["api_flow"] = api_flow

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


def pipeline_bin_settings(_cfg: dict | None = None) -> dict[str, bool]:
    block = load_local().get("pipeline") or {}
    raw = block.get("bin_toggles") if isinstance(block, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {p: bool(raw.get(p, False)) for p in PIPELINE_BIN_PREFIXES}


def apply_pipeline_bin_filters(
    toggles: dict[str, bool] | None = None,
    *,
    prefixes: list[str] | None = None,
) -> dict[str, bool]:
    current = pipeline_bin_settings()
    if prefixes is not None:
        wanted = {
            "".join(ch for ch in str(p) if ch.isdigit())
            for p in prefixes
            if str(p).strip()
        }
        current = {p: p in wanted for p in PIPELINE_BIN_PREFIXES}
    elif isinstance(toggles, dict):
        for key, val in toggles.items():
            digits = "".join(ch for ch in str(key) if ch.isdigit())
            if digits in PIPELINE_BIN_PREFIXES:
                current[digits] = bool(val)
    _patch_section("pipeline", bin_toggles=current)
    return current


def _load_decline_config() -> dict:
    import yaml

    path = DECLINE_CONFIG
    if not path.is_file() and DECLINE_EXAMPLE.is_file():
        path.write_bytes(DECLINE_EXAMPLE.read_bytes())
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _fmt_opt_amount(raw: object) -> str:
    if raw in (None, ""):
        return ""
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return ""
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def redirect_filter_settings(_cfg: dict | None = None) -> dict[str, bool]:
    from core.deals_ui_local import redirect_ui_filters

    return redirect_ui_filters()


def apply_redirect_filters(
    *,
    skip_bog: bool | None = None,
    visa_only: bool | None = None,
    max_remaining: bool | None = None,
) -> dict[str, bool]:
    """Локально runtime/deals_ui.yaml — не shared config."""
    fields: dict[str, object] = {}
    if skip_bog is not None:
        fields["skip_bog"] = bool(skip_bog)
    if visa_only is not None:
        fields["visa_only"] = bool(visa_only)
    if max_remaining is not None:
        fields["max_remaining"] = bool(max_remaining)
    if fields:
        _patch_section("redirect", **fields)
    return redirect_filter_settings()


def redirect_bin_settings(_cfg: dict | None = None) -> dict[str, bool]:
    block = load_local().get("redirect") or {}
    raw = block.get("bin_toggles") if isinstance(block, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {p: bool(raw.get(p, False)) for p in REDIRECT_BIN_PREFIXES}


def apply_redirect_bin_filters(
    toggles: dict[str, bool] | None = None,
    *,
    prefixes: list[str] | None = None,
) -> dict[str, bool]:
    current = redirect_bin_settings()
    if prefixes is not None:
        wanted = {
            "".join(ch for ch in str(p) if ch.isdigit())
            for p in prefixes
            if str(p).strip()
        }
        current = {p: p in wanted for p in REDIRECT_BIN_PREFIXES}
    elif isinstance(toggles, dict):
        for key, val in toggles.items():
            digits = "".join(ch for ch in str(key) if ch.isdigit())
            if digits in REDIRECT_BIN_PREFIXES:
                current[digits] = bool(val)
    _patch_section("redirect", bin_toggles=current)
    return current


def redirect_amount_settings(_cfg: dict | None = None) -> dict[str, str]:
    block = load_local().get("redirect") or {}
    return {
        "max_per_run": str(block.get("max_per_run") or "5"),
        "min_amount": _fmt_opt_amount(block.get("min_amount")),
        "max_amount": _fmt_opt_amount(block.get("max_amount")),
    }


def apply_redirect_amounts(
    *,
    max_per_run: int | str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    clear_min_amount: bool = False,
    clear_max_amount: bool = False,
) -> None:
    fields: dict[str, object] = {}
    if max_per_run is not None:
        fields["max_per_run"] = str(max(1, int(max_per_run)))
    if clear_min_amount:
        fields["min_amount"] = ""
    elif min_amount is not None:
        fields["min_amount"] = _fmt_opt_amount(min_amount)
    if clear_max_amount:
        fields["max_amount"] = ""
    elif max_amount is not None:
        fields["max_amount"] = _fmt_opt_amount(max_amount)
    if fields:
        _patch_section("redirect", **fields)


def decline_bin_settings(_cfg: dict | None = None) -> dict[str, bool]:
    block = load_local().get("decline") or {}
    raw = block.get("bin_toggles") if isinstance(block, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {p: bool(raw.get(p, True)) for p in DECLINE_BIN_PREFIXES}


def decline_tbc_enabled(_cfg: dict | None = None) -> bool:
    block = load_local().get("decline") or {}
    if "tbc" not in block:
        return True
    return bool(block.get("tbc"))


def decline_max_per_run(_cfg: dict | None = None) -> int:
    block = load_local().get("decline") or {}
    raw = block.get("max_per_run", DECLINE_DEFAULT_PER_RUN)
    return clamp_decline_limit(raw)


def decline_amount_settings(_cfg: dict | None = None) -> dict[str, str]:
    block = load_local().get("decline") or {}
    return {
        "min_amount": _fmt_opt_amount(block.get("min_amount")),
        "max_amount": _fmt_opt_amount(block.get("max_amount")),
    }


def apply_decline_bin_filters(
    toggles: dict[str, bool] | None = None,
    *,
    prefixes: list[str] | None = None,
    tbc: bool | None = None,
    max_per_run: int | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    clear_min_amount: bool = False,
    clear_max_amount: bool = False,
) -> dict[str, bool]:
    """Локально runtime/deals_ui.yaml — не shared config."""
    current = decline_bin_settings()
    if prefixes is not None:
        wanted = {
            "".join(ch for ch in str(p) if ch.isdigit())
            for p in prefixes
            if str(p).strip()
        }
        current = {p: p in wanted for p in DECLINE_BIN_PREFIXES}
    elif isinstance(toggles, dict):
        for key, val in toggles.items():
            digits = "".join(ch for ch in str(key) if ch.isdigit())
            if digits in DECLINE_BIN_PREFIXES:
                current[digits] = bool(val)
    fields: dict[str, object] = {"bin_toggles": current}
    if max_per_run is not None:
        fields["max_per_run"] = str(clamp_decline_limit(max_per_run))
    if tbc is not None:
        fields["tbc"] = bool(tbc)
    if clear_min_amount:
        fields["min_amount"] = ""
    elif min_amount is not None:
        fields["min_amount"] = _fmt_opt_amount(min_amount)
    if clear_max_amount:
        fields["max_amount"] = ""
    elif max_amount is not None:
        fields["max_amount"] = _fmt_opt_amount(max_amount)
    _patch_section("decline", **fields)
    return current
