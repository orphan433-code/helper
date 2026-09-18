"""Отдельные Chrome-профили и кэш токена: HZ и EasySend."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from core.decline_hosts import (
    DECLINE_SERVICE_EZE,
    DECLINE_SERVICE_HZ,
    DECLINE_SERVICE_URLS,
    normalize_decline_service,
)
from core.paths import ROOT, RUNTIME_DIR

_PROBE: dict[str, tuple[float, bool]] = {}
_STATUS: tuple[float, dict[str, bool]] | None = None
_STATUS_TTL_SEC = 20.0
_CHECKING: dict[str, bool] = {
    DECLINE_SERVICE_HZ: False,
    DECLINE_SERVICE_EZE: False,
}


def service_from_url(url: object) -> str:
    text = str(url or "").strip().lower()
    if "e.hz." in text or "easysend" in text:
        return DECLINE_SERVICE_EZE
    return DECLINE_SERVICE_HZ


def pay_out_url(service: object = None) -> str:
    key = normalize_decline_service(service)
    return f"{DECLINE_SERVICE_URLS[key]}/pay-out?status=new"


def token_cache_path(service: object = None) -> Path:
    key = normalize_decline_service(service)
    name = "eze_token.txt" if key == DECLINE_SERVICE_EZE else "platcore_token.txt"
    return RUNTIME_DIR / name


def jwt_host_marker(service: object = None) -> str:
    """Игла в Chrome-профиле. e.hz не путать с hz: ://hz. ≠ ://e.hz."""
    key = normalize_decline_service(service)
    if key == DECLINE_SERVICE_EZE:
        return "e.hz.temkitemki"
    return "://hz.temkitemki"


def jwt_host_needles(service: object = None) -> tuple[str, ...]:
    key = normalize_decline_service(service)
    if key == DECLINE_SERVICE_EZE:
        return ("e.hz.temkitemki", "easysendglobal")
    return ("://hz.temkitemki",)


def profile_dir(cfg: dict | None = None, *, service: object = None) -> Path:
    """HZ: browser.user_data_dir. Easy: user_data_dir_eze или соседняя *_eze."""
    cfg = cfg if isinstance(cfg, dict) else {}
    browser = cfg.get("browser") or {}
    hz_raw = str(browser.get("user_data_dir") or "../CNY/browser_profile")
    key = normalize_decline_service(service)
    if key != DECLINE_SERVICE_EZE:
        raw = hz_raw
    else:
        raw = str(browser.get("user_data_dir_eze") or "").strip()
        if not raw:
            hz_path = Path(hz_raw)
            raw = str(hz_path.parent / f"{hz_path.name}_eze")
    path = Path(raw)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def read_cached_token(service: object = None) -> str | None:
    path = token_cache_path(service)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return text or None


def write_cached_token(token: str, *, service: object = None) -> None:
    path = token_cache_path(service)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    mark_session_ok(service, True)
    invalidate_session_status()


def mark_session_ok(service: object, ok: bool) -> None:
    key = normalize_decline_service(service)
    _PROBE[key] = (time.monotonic(), bool(ok))


def invalidate_session_status() -> None:
    global _STATUS
    _STATUS = None


def set_session_checking(service: object | None = None, checking: bool = False) -> None:
    flag = bool(checking)
    if service is None:
        _CHECKING[DECLINE_SERVICE_HZ] = flag
        _CHECKING[DECLINE_SERVICE_EZE] = flag
        return
    _CHECKING[normalize_decline_service(service)] = flag


def session_status_stale(*, ttl: float | None = None) -> bool:
    limit = _STATUS_TTL_SEC if ttl is None else float(ttl)
    if _STATUS is None:
        return True
    return time.monotonic() - _STATUS[0] >= limit


def session_unprobed() -> bool:
    return _STATUS is None


def session_status_snapshot() -> dict[str, Any]:
    """Последние флаги без HTTP. До первой пробы — checking, не «онлайн»."""
    if _STATUS is not None:
        flags = dict(_STATUS[1])
    else:
        flags = {"login_hz_ok": False, "login_eze_ok": False}
    hz_chk = bool(_CHECKING.get(DECLINE_SERVICE_HZ))
    eze_chk = bool(_CHECKING.get(DECLINE_SERVICE_EZE))
    if _STATUS is None and not hz_chk and not eze_chk:
        hz_chk = True
        eze_chk = True
    flags["login_hz_checking"] = hz_chk
    flags["login_eze_checking"] = eze_chk
    return flags


def findnew_ok(base_url: str, token: str, *, timeout_sec: float = 5.0) -> bool:
    """findNew без ретраев и без Panic — для индикатора входа."""
    if not token:
        return False
    origin = str(base_url or "").rstrip("/")
    url = (
        f"{origin}/api/deals/findNew?page=1&limit=1"
        f"&status=new&type=buyAll"
    )
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Origin": origin,
            "Referer": f"{origin}/pay-out",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if int(resp.status) != 200:
                return False
            raw = resp.read() or b""
            data = json.loads(raw.decode("utf-8")) if raw else None
            return isinstance(data, dict)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _host_ok(service: str, token: str | None) -> bool:
    if not token:
        return False
    return findnew_ok(DECLINE_SERVICE_URLS[service], token)


def _compute_session_status() -> dict[str, bool]:
    """Два аккаунта: токен HZ не копируем в e.hz и наоборот."""
    hz_tok = read_cached_token(DECLINE_SERVICE_HZ)
    eze_tok = read_cached_token(DECLINE_SERVICE_EZE)
    hz_ok = _host_ok(DECLINE_SERVICE_HZ, hz_tok)
    eze_ok = _host_ok(DECLINE_SERVICE_EZE, eze_tok)
    mark_session_ok(DECLINE_SERVICE_HZ, hz_ok)
    mark_session_ok(DECLINE_SERVICE_EZE, eze_ok)
    return {"login_hz_ok": hz_ok, "login_eze_ok": eze_ok}


def session_ok(service: object, *, force: bool = False) -> bool:
    key = normalize_decline_service(service)
    payload = session_status_payload(force=force)
    if key == DECLINE_SERVICE_EZE:
        return bool(payload.get("login_eze_ok"))
    return bool(payload.get("login_hz_ok"))


def session_status_payload(*, force: bool = False) -> dict[str, Any]:
    global _STATUS
    now = time.monotonic()
    if not force and _STATUS is not None and now - _STATUS[0] < _STATUS_TTL_SEC:
        return session_status_snapshot()
    payload = _compute_session_status()
    payload["login_hz_checking"] = bool(_CHECKING.get(DECLINE_SERVICE_HZ))
    payload["login_eze_checking"] = bool(_CHECKING.get(DECLINE_SERVICE_EZE))
    _STATUS = (now, {"login_hz_ok": payload["login_hz_ok"], "login_eze_ok": payload["login_eze_ok"]})
    return dict(payload)
