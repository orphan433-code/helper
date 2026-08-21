#!/usr/bin/env python3
"""Сохранение настроек из GUI в config.yaml."""

from __future__ import annotations

from core.config import load_config, save_config
from core.decline_bins import DECLINE_BIN_PREFIXES, DECLINE_MAX_PER_RUN
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


def _save_decline_config(cfg: dict) -> None:
    import yaml

    DECLINE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with DECLINE_CONFIG.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)


def redirect_filter_settings(cfg: dict | None = None) -> dict[str, bool]:
    """Фильтры редиректа из platcore-decline/config.yaml."""
    data = cfg if isinstance(cfg, dict) else _load_decline_config()
    red = data.get("bank_redirect") or {}
    return {
        "skip_bog": bool(red.get("skip_bog", False)),
        "visa_only": bool(red.get("visa_only", False)),
        "max_remaining": bool(red.get("max_remaining", False)),
    }


def apply_redirect_filters(
    *,
    skip_bog: bool | None = None,
    visa_only: bool | None = None,
    max_remaining: bool | None = None,
) -> dict[str, bool]:
    """Сохранить фильтры редиректа в platcore-decline/config.yaml."""
    cfg = _load_decline_config()
    red = dict(cfg.get("bank_redirect") or {})
    if skip_bog is not None:
        red["skip_bog"] = bool(skip_bog)
    if visa_only is not None:
        red["visa_only"] = bool(visa_only)
    if max_remaining is not None:
        red["max_remaining"] = bool(max_remaining)
    cfg["bank_redirect"] = red
    _save_decline_config(cfg)
    return redirect_filter_settings(cfg)


def decline_bin_settings(cfg: dict | None = None) -> dict[str, bool]:
    """Тумблеры BIN отмены из platcore-decline/config.yaml."""
    data = cfg if isinstance(cfg, dict) else _load_decline_config()
    decline = data.get("bank_decline") or {}
    raw = decline.get("bin_toggles") if isinstance(decline, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {p: bool(raw.get(p, True)) for p in DECLINE_BIN_PREFIXES}


def decline_tbc_enabled(cfg: dict | None = None) -> bool:
    """Тумблер TBC отмены. Нет ключа в конфиге — включён."""
    data = cfg if isinstance(cfg, dict) else _load_decline_config()
    decline = data.get("bank_decline") or {}
    if not isinstance(decline, dict) or "tbc" not in decline:
        return True
    return bool(decline.get("tbc"))


def apply_decline_bin_filters(
    toggles: dict[str, bool] | None = None,
    *,
    prefixes: list[str] | None = None,
    tbc: bool | None = None,
) -> dict[str, bool]:
    """Сохранить тумблеры BIN отмены. prefixes = включённые, остальные выкл."""
    cfg = _load_decline_config()
    decline = dict(cfg.get("bank_decline") or {})
    current = decline_bin_settings(cfg)
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
    decline["bin_toggles"] = current
    decline["max_per_run"] = DECLINE_MAX_PER_RUN
    if tbc is not None:
        decline["tbc"] = bool(tbc)
    cfg["bank_decline"] = decline
    _save_decline_config(cfg)
    return current
