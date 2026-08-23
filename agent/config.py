"""Настройки AI-агента (Gemini)."""

from __future__ import annotations

import os
from typing import Any

from core.config import load_config

DEFAULT_MODEL = "gemini-2.0-flash"


def agent_settings() -> dict[str, Any]:
    cfg = load_config()
    block = cfg.get("agent") or {}
    if not isinstance(block, dict):
        block = {}
    key = (
        str(block.get("gemini_api_key") or "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    model = str(block.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    verbose = block.get("verbose")
    if verbose is None:
        verbose = True
    return {
        "gemini_api_key": key,
        "model": model,
        "enabled": bool(key),
        "verbose": bool(verbose),
    }


def agent_configured() -> bool:
    return bool(agent_settings()["gemini_api_key"])
