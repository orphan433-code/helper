"""Локальные настройки редиректа/отмены — runtime/deals_ui.yaml, не в shared config."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from core.decline_bins import DECLINE_BIN_PREFIXES, DECLINE_DEFAULT_PER_RUN
from core.paths import ROOT
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES, normalize_redirect_prefixes

LOCAL_PATH = ROOT / "runtime" / "deals_ui.yaml"

_DEFAULT: dict[str, Any] = {
    "pipeline": {
        "bin_toggles": {p: False for p in PIPELINE_BIN_PREFIXES},
    },
    "redirect": {
        "skip_bog": False,
        "visa_only": False,
        "max_remaining": False,
        "max_per_run": "5",
        "min_amount": "",
        "max_amount": "",
        "bin_toggles": {p: False for p in REDIRECT_BIN_PREFIXES},
    },
    "decline": {
        "tbc": True,
        "max_per_run": str(DECLINE_DEFAULT_PER_RUN),
        "min_amount": "",
        "max_amount": "",
        "bin_toggles": {p: True for p in DECLINE_BIN_PREFIXES},
    },
}


def _ensure_file() -> None:
    if LOCAL_PATH.is_file():
        return
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_local(deepcopy(_DEFAULT))


def load_local() -> dict[str, Any]:
    _ensure_file()
    with LOCAL_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        data = {}
    out = deepcopy(_DEFAULT)
    for section in ("pipeline", "redirect", "decline"):
        raw = data.get(section)
        if not isinstance(raw, dict):
            continue
        block = out[section]
        for key, val in raw.items():
            if key == "bin_toggles" and isinstance(val, dict):
                if section == "pipeline":
                    prefixes = PIPELINE_BIN_PREFIXES
                elif section == "redirect":
                    prefixes = REDIRECT_BIN_PREFIXES
                else:
                    prefixes = DECLINE_BIN_PREFIXES
                block["bin_toggles"] = {
                    p: bool(val.get(p, block["bin_toggles"].get(p, False)))
                    for p in prefixes
                }
            elif key in block:
                block[key] = val
    return out


def save_local(data: dict[str, Any]) -> None:
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _patch_section(section: str, **fields: Any) -> dict[str, Any]:
    data = load_local()
    block = dict(data.get(section) or _DEFAULT[section])
    for key, val in fields.items():
        if val is None:
            continue
        if key == "bin_toggles" and isinstance(val, dict):
            block["bin_toggles"] = dict(val)
        else:
            block[key] = val
    data[section] = block
    save_local(data)
    return block


def pipeline_ui_bin_prefixes() -> list[str]:
    """Включённые BIN основного пайплайна из runtime/deals_ui.yaml."""
    block = load_local().get("pipeline") or {}
    raw = block.get("bin_toggles")
    if not isinstance(raw, dict):
        raw = {}
    return [p for p in PIPELINE_BIN_PREFIXES if raw.get(p)]


def redirect_ui_filters() -> dict[str, bool]:
    """Тумблеры редиректа из runtime/deals_ui.yaml."""
    block = load_local().get("redirect") or {}
    return {
        "skip_bog": bool(block.get("skip_bog", False)),
        "visa_only": bool(block.get("visa_only", False)),
        "max_remaining": bool(block.get("max_remaining", False)),
    }


def redirect_ui_bin_prefixes() -> list[str]:
    """Включённые BIN редиректа из runtime/deals_ui.yaml."""
    block = load_local().get("redirect") or {}
    raw = block.get("bin_toggles")
    if not isinstance(raw, dict):
        raw = {}
    return [p for p in REDIRECT_BIN_PREFIXES if raw.get(p)]


def resolve_redirect_bin_prefixes(
    cli_prefixes: object = None,
    *,
    strict_cli: bool = False,
) -> list[str]:
    """BIN редиректа: CLI (если передан) или runtime/deals_ui.yaml."""
    local_bins = redirect_ui_bin_prefixes()
    if cli_prefixes is None:
        return local_bins
    if isinstance(cli_prefixes, str):
        items = cli_prefixes.split(",")
    elif isinstance(cli_prefixes, (list, tuple)):
        items = list(cli_prefixes)
    else:
        items = []
    cli_bins = normalize_redirect_prefixes(items)
    if items and strict_cli and not cli_bins:
        raise SystemExit(
            "Неизвестный BIN редиректа. Доступны: "
            + ", ".join(REDIRECT_BIN_PREFIXES)
        )
    if cli_bins:
        return cli_bins
    return local_bins
