"""Хост отмены: HZ или e.hz (Easy). Редирект всегда HZ."""

from __future__ import annotations

from urllib.parse import urlparse

DECLINE_SERVICE_HZ = "hz"
DECLINE_SERVICE_EZE = "eze"
DECLINE_SERVICE_URLS = {
    DECLINE_SERVICE_HZ: "https://hz.temkitemki.work",
    DECLINE_SERVICE_EZE: "https://e.hz.temkitemki.work",
}
_EZE_ALIASES = frozenset(
    {"eze", "easysend", "easy", "easysendglobal", "e.hz", "ehz"}
)


def normalize_decline_service(raw: object) -> str:
    key = str(raw or "").strip().lower()
    if key in _EZE_ALIASES:
        return DECLINE_SERVICE_EZE
    return DECLINE_SERVICE_HZ


def hz_api_base_url(cfg: dict | None = None) -> str:
    cfg = cfg if isinstance(cfg, dict) else {}
    decline = cfg.get("bank_decline") or {}
    explicit = str(decline.get("api_base_url") or "").strip().rstrip("/")
    if explicit:
        return explicit
    monitor = str((cfg.get("dashboard") or {}).get("monitor_url") or "").strip()
    if monitor:
        parsed = urlparse(monitor)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return DECLINE_SERVICE_URLS[DECLINE_SERVICE_HZ]


def decline_api_base_url(
    cfg: dict | None = None,
    *,
    service: object = None,
    redirect: bool = False,
) -> str:
    """EZE только для отмены. Редирект и HZ — прежний origin."""
    if redirect:
        return hz_api_base_url(cfg)
    if normalize_decline_service(service) == DECLINE_SERVICE_EZE:
        return DECLINE_SERVICE_URLS[DECLINE_SERVICE_EZE]
    return hz_api_base_url(cfg)
