"""PlatCore API для agent preview — тот же путь токена что decline/redirect."""

from __future__ import annotations

import sys
from copy import deepcopy
from typing import Any

from core.paths import ROOT

_DECLINE_DIR = ROOT / "platcore-decline"
if str(_DECLINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DECLINE_DIR))

import decline_by_bank_api as dapi  # noqa: E402


def load_decline_config() -> dict[str, Any]:
    """Тот же config.yaml что subprocess decline_by_bank_api.py."""
    return dapi.load_config()


async def acquire_token(
    cfg: dict[str, Any] | None = None,
    *,
    service: str | None = None,
    redirect: bool = False,
) -> tuple[str, str, str]:
    """
    Токен как у рабочего decline: кэш входа (eze_token / platcore_token).
    Preview всегда headless — без видимого Chrome.
    """
    from core.host_session import service_from_url

    base_cfg = cfg or load_decline_config()
    preview_cfg = deepcopy(base_cfg)
    browser = dict(preview_cfg.get("browser") or {})
    browser["headless"] = True
    preview_cfg["browser"] = browser

    base_url = dapi._api_base_url(
        preview_cfg,
        service=service,
        redirect=redirect,
    )
    host = "EasySend" if service_from_url(base_url) == "eze" else "HZ"
    source = f"cache {host}"

    token = await dapi.resolve_token(preview_cfg, base_url)
    return token, base_url, source
