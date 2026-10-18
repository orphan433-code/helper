"""Локальные настройки редиректа/отмены — runtime/deals_ui.yaml, не в shared config."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from core.decline_bins import (
    DECLINE_BIN_PREFIXES,
    DECLINE_DEFAULT_ON,
    DECLINE_DEFAULT_PER_RUN,
)
from core.decline_hosts import normalize_decline_service
from core.paths import ROOT
from core.pipeline_bins import PIPELINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES, normalize_redirect_prefixes

LOCAL_PATH = ROOT / "runtime" / "deals_ui.yaml"

def _pipeline_block() -> dict[str, Any]:
    return {
        "bin_toggles": {p: False for p in PIPELINE_BIN_PREFIXES},
        "service": "hz",
        "dry_stop_before_pay": False,
        "skip_tbc": True,
        "skip_bog": True,
        "skip_tjk": True,
        "max_deals": 5,
        "empty_passes": 2,
        "min_amount": "",
        "max_amount": "",
        "allow_visa": True,
        "allow_mastercard": False,
        "currencies": [],
        "from_pending": False,
    }


_DEFAULT: dict[str, Any] = {
    "pipeline": _pipeline_block(),
    "alif": _pipeline_block(),
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
        "service": "hz",
        "bin_toggles": {p: p in DECLINE_DEFAULT_ON for p in DECLINE_BIN_PREFIXES},
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
    for section in ("pipeline", "alif", "redirect", "decline"):
        raw = data.get(section)
        if not isinstance(raw, dict):
            continue
        block = out[section]
        for key, val in raw.items():
            if key == "bin_toggles" and isinstance(val, dict):
                if section in ("pipeline", "alif"):
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


def _run_section() -> str:
    """Во время цикла Alif читаем его блок. Экран Activ всегда смотрит pipeline."""
    from core.payout_bank import is_alif

    return "alif" if is_alif() else "pipeline"


def _run_block() -> dict[str, Any]:
    block = load_local().get(_run_section()) or {}
    return block if isinstance(block, dict) else {}


def alif_saved_block() -> dict[str, Any]:
    block = load_local().get("alif") or {}
    return block if isinstance(block, dict) else {}


def _bin_prefixes(block: dict[str, Any]) -> list[str]:
    raw = block.get("bin_toggles")
    if not isinstance(raw, dict):
        raw = {}
    return [p for p in PIPELINE_BIN_PREFIXES if raw.get(p)]


def pipeline_ui_bin_prefixes() -> list[str]:
    """Включённые BIN текущего цикла (Activ или Alif)."""
    return _bin_prefixes(_run_block())


def pipeline_ui_service() -> str:
    """Хост текущего цикла: hz | eze."""
    return normalize_decline_service(_run_block().get("service"))


def pipeline_saved_service() -> str:
    """Хост вкладки Activ, без подмены на время цикла Alif."""
    block = load_local().get("pipeline") or {}
    return normalize_decline_service(block.get("service") if isinstance(block, dict) else None)


def pipeline_ui_dry_stop() -> bool:
    """Тест: форма + сверка, без «Подтвердить и перевести» / SMS."""
    return bool(_run_block().get("dry_stop_before_pay"))


def pipeline_saved_dry_stop() -> bool:
    block = load_local().get("pipeline") or {}
    return bool(block.get("dry_stop_before_pay")) if isinstance(block, dict) else False


def pipeline_ui_skip_tbc() -> bool:
    """Пропуск всего TBC (Visa+MC) на Accept. Default вкл."""
    return bool(_run_block().get("skip_tbc", True))


def pipeline_saved_skip_tbc() -> bool:
    block = load_local().get("pipeline") or {}
    return bool(block.get("skip_tbc", True)) if isinstance(block, dict) else True


def pipeline_ui_skip_bog() -> bool:
    """Пропуск всего BOG (Visa+MC) на Accept. Default вкл."""
    return bool(_run_block().get("skip_bog", True))


def pipeline_saved_skip_bog() -> bool:
    block = load_local().get("pipeline") or {}
    return bool(block.get("skip_bog", True)) if isinstance(block, dict) else True


def pipeline_ui_skip_tjk() -> bool:
    """Пропуск ТЖК (548028…) на Accept. Default вкл."""
    return bool(_run_block().get("skip_tjk", True))


def pipeline_saved_skip_tjk() -> bool:
    block = load_local().get("pipeline") or {}
    return bool(block.get("skip_tjk", True)) if isinstance(block, dict) else True


def decline_ui_service() -> str:
    """Хост отмены из runtime/deals_ui.yaml: hz | eze."""
    block = load_local().get("decline") or {}
    return normalize_decline_service(block.get("service"))


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


def _opt_amount(raw: object) -> float | None:
    text = str(raw or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def overlay_alif_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """Копия cfg с лимитами вкладки Alif. Файл Activ не пишем."""
    block = alif_saved_block()
    out = deepcopy(cfg)
    pipe = dict(out.get("pipeline") or {})
    try:
        deals = int(block.get("max_deals") or pipe.get("max_deals_per_run") or 5)
    except (TypeError, ValueError):
        deals = 5
    pipe["max_deals_per_run"] = max(1, min(50, deals))
    try:
        passes = int(block.get("empty_passes") or pipe.get("max_empty_list_passes") or 2)
    except (TypeError, ValueError):
        passes = 2
    pipe["max_empty_list_passes"] = max(1, min(20, passes))
    pipe["from_pending"] = bool(block.get("from_pending", False))
    out["pipeline"] = pipe

    api = dict(out.get("api_flow") or {})
    api["max_deals"] = pipe["max_deals_per_run"]
    raw_cur = block.get("currencies")
    if isinstance(raw_cur, list):
        api["currencies"] = [str(c).strip().upper() for c in raw_cur if str(c).strip()]
    out["api_flow"] = api

    val = dict(out.get("validation") or {})
    val["allow_visa"] = bool(block.get("allow_visa", True))
    val["allow_mastercard"] = bool(block.get("allow_mastercard", False))
    lo = _opt_amount(block.get("min_amount"))
    hi = _opt_amount(block.get("max_amount"))
    if lo is None:
        val.pop("min_amount", None)
    else:
        val["min_amount"] = lo
    if hi is None:
        val.pop("max_amount", None)
    else:
        val["max_amount"] = hi
    out["validation"] = val
    return out
