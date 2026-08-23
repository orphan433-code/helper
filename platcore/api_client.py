"""PlatCore HTTP — как редирект: токен с профиля, потом urllib. Окно не держим."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.logkit import info, warn
from core.paths import ROOT, RUNTIME_DIR
from core.validators import PanicError

_FIND_NEW_TYPE = "buyAll"
_FIND_NEW_LIMIT = 100
_TOKEN_CACHE = RUNTIME_DIR / "platcore_token.txt"
_JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
)
_TOKEN_KEYS = (
    "token",
    "accessToken",
    "access_token",
    "authToken",
    "jwt",
    "bearer",
    "platcore_token",
)


def api_base_url(cfg: dict) -> str:
    flow = cfg.get("api_flow") or {}
    explicit = str(flow.get("api_base_url") or "").strip().rstrip("/")
    if explicit:
        return explicit
    decline = cfg.get("bank_decline") or {}
    explicit = str(decline.get("api_base_url") or "").strip().rstrip("/")
    if explicit:
        return explicit
    monitor = str((cfg.get("dashboard") or {}).get("monitor_url") or "").strip()
    if monitor:
        parsed = urlparse(monitor)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return "https://hz.temkitemki.work"


def base_origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://hz.temkitemki.work"


def _strip_bearer(raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def _profile_dir(cfg: dict):
    from pathlib import Path

    raw = str((cfg.get("browser") or {}).get("user_data_dir") or "../CNY/browser_profile")
    return (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw)


def _save_token(token: str) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(token, encoding="utf-8")


def _token_from_env_cfg(cfg: dict) -> str | None:
    flow = cfg.get("api_flow") or {}
    decline = cfg.get("bank_decline") or {}
    for key in (
        flow.get("token"),
        decline.get("token"),
        os.environ.get("PLATCORE_TOKEN"),
    ):
        if key and str(key).strip():
            return _strip_bearer(str(key))
    return None


def _token_from_cache() -> str | None:
    if not _TOKEN_CACHE.is_file():
        return None
    text = _TOKEN_CACHE.read_text(encoding="utf-8").strip()
    return _strip_bearer(text) if text else None


def _jwts_from_hz_blob(data: bytes) -> list[str]:
    """JWT только рядом с hz.temkitemki — не любой токен из Chrome."""
    found: list[str] = []
    for enc in ("utf-8", "utf-16-le"):
        try:
            text = data.decode(enc, errors="ignore")
        except Exception:
            continue
        if "temkitemki" not in text.lower():
            continue
        found.extend(_JWT_RE.findall(text))
    # длинный обычно access, короткий — мусор
    uniq = sorted(set(found), key=len, reverse=True)
    return uniq


def _tokens_from_profile_disk(cfg: dict) -> list[str]:
    profile = _profile_dir(cfg)
    dirs = [
        profile / "Default" / "Local Storage" / "leveldb",
        profile / "Default" / "Session Storage",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for folder in dirs:
        if not folder.is_dir():
            continue
        files = sorted(
            (p for p in folder.iterdir() if p.suffix in {".log", ".ldb"} or p.name == "LOG"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        for path in files:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            for tok in _jwts_from_hz_blob(data):
                if tok not in seen:
                    seen.add(tok)
                    out.append(tok)
    return out


async def _token_from_headless(cfg: dict, base_url: str) -> str | None:
    """Как редирект: headless на секунду, localStorage, закрыть."""
    from playwright.async_api import async_playwright

    profile = _profile_dir(cfg)
    keys_json = json.dumps(list(_TOKEN_KEYS))
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=True,
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                f"{base_url}/pay-out?status=new",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(1200)
            token = await page.evaluate(
                f"""() => {{
                    const keys = {keys_json};
                    for (const k of keys) {{
                        const v = localStorage.getItem(k) || sessionStorage.getItem(k);
                        if (v && v.length > 20) return v;
                    }}
                    for (const store of [localStorage, sessionStorage]) {{
                        for (let i = 0; i < store.length; i++) {{
                            const k = store.key(i);
                            const v = store.getItem(k);
                            if (!v || v.length < 40) continue;
                            if (v.split('.').length === 3) return v;
                        }}
                    }}
                    return null;
                }}"""
            )
            return _strip_bearer(token) if token else None
        finally:
            await context.close()


async def prime_hz_ledger(
    cfg: dict,
    base_url: str,
    deal_id: str,
    token: str,
    order_id: str,
) -> bool:
    """Видимый Chrome, тот же browser_profile: сделка → Approve → hz-calc POST."""
    from core.human import parse_human_timing
    from platcore.completion import ensure_completion_deal_ready
    from playwright.async_api import async_playwright

    profile = _profile_dir(cfg)
    url = f"{base_url}/pay-out?limit=100&status=pending&dealId={deal_id}"
    info(f"hz-calc: открываю окно {order_id} (профиль {profile.name})")
    posted = False
    keys_json = json.dumps(list(_TOKEN_KEYS))
    timing = parse_human_timing(cfg)
    zoom = (cfg.get("browser") or {}).get("page_zoom")
    async with async_playwright() as playwright:
        try:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                viewport={"width": 1400, "height": 900},
                locale="ru-RU",
            )
        except Exception as exc:
            warn(f"hz-calc: профиль занят ({exc}). Закрой другой Chrome с CNY")
            return False
        try:
            page = context.pages[0] if context.pages else await context.new_page()

            def _on_response(resp) -> None:
                nonlocal posted
                if "/_hz/ledger" in (resp.url or "") and resp.request.method == "POST":
                    posted = True

            page.on("response", _on_response)
            await page.add_init_script(
                f"""() => {{
                    const tok = {json.dumps(token)};
                    const keys = {keys_json};
                    for (const k of keys) {{
                        try {{
                            localStorage.setItem(k, tok);
                            sessionStorage.setItem(k, tok);
                        }} catch (e) {{}}
                    }}
                }}"""
            )
            try:
                await page.bring_to_front()
            except Exception:
                pass
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if zoom:
                try:
                    await page.evaluate(f"() => {{ document.body.style.zoom = '{zoom}'; }}")
                except Exception:
                    pass
            try:
                # Как ретрай чеков: goto dealId → Order info → Approve
                await page.wait_for_timeout(1000)
                await ensure_completion_deal_ready(page, timing=timing)
                info("hz-calc: Approve как на ретрае чеков")
            except Exception as exc:
                warn(f"hz-calc: Approve не нажат ({exc})")
            try:
                await page.wait_for_selector("#hz-calc", timeout=20_000)
                info("hz-calc: виджет на странице")
            except Exception:
                warn(f"hz-calc: #hz-calc нет, url={page.url}")
            for _ in range(80):
                if posted:
                    break
                await page.wait_for_timeout(250)
            if posted:
                await page.wait_for_timeout(1500)
        finally:
            await context.close()
    if posted:
        info("hz-calc: POST /_hz/ledger ушёл")
    else:
        warn("hz-calc: POST не ушёл — смотри окно, что на экране")
    return posted


def token_works(base_url: str, token: str) -> bool:
    url = (
        f"{base_url}/api/deals/findNew?page=1&limit=1"
        f"&status=new&type={_FIND_NEW_TYPE}"
    )
    code, data = http_json("GET", url, token)
    return code == 200 and isinstance(data, dict)


async def resolve_token(cfg: dict, base_url: str) -> str:
    """Как редирект: токен → проверка findNew. Headless только если кэш мёртвый."""
    ordered: list[tuple[str, str]] = []
    env = _token_from_env_cfg(cfg)
    if env:
        ordered.append(("env", env))
    cached = _token_from_cache()
    if cached:
        ordered.append(("cache", cached))

    def _try(source: str, token: str) -> bool:
        if token_works(base_url, token):
            info(f"Токен ок ({source})")
            _save_token(token)
            return True
        info(f"Токен {source} не принят")
        return False

    for source, token in ordered:
        if _try(source, token):
            return token

    try:
        headless = await _token_from_headless(cfg, base_url)
    except Exception as exc:
        warn(f"Токен headless: {exc}")
        headless = None
    if headless and _try("headless", headless):
        return headless
    for disk in _tokens_from_profile_disk(cfg):
        if _try("disk", disk):
            return disk
    if _TOKEN_CACHE.is_file():
        _TOKEN_CACHE.unlink()
    raise PanicError(
        "findNew 401: токен не подошёл. "
        "Закрой Chrome с профилем CNY и жми цикл ещё раз "
        "(снимем токен как редирект) или задай PLATCORE_TOKEN."
    )


def http_json(
    method: str,
    url: str,
    token: str | None = None,
    *,
    body: dict | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Accept": "application/json",
        "Origin": base_origin(url),
        "Referer": f"{base_origin(url)}/pay-out",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, None
            return resp.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        return exc.code, detail


def fetch_find_new(
    base_url: str,
    token: str,
    *,
    status: str = "new",
    page_no: int = 1,
    limit: int = _FIND_NEW_LIMIT,
) -> dict[str, Any]:
    url = (
        f"{base_url}/api/deals/findNew?page={page_no}&limit={limit}"
        f"&status={status}&type={_FIND_NEW_TYPE}"
    )
    code, data = http_json("GET", url, token)
    if code != 200 or not isinstance(data, dict):
        raise PanicError(f"findNew {status}: HTTP {code}")
    return data


def fetch_find_new_rows(
    base_url: str, token: str, *, status: str = "new"
) -> list[dict[str, Any]]:
    first = fetch_find_new(base_url, token, status=status, page_no=1)
    rows = list(first.get("rows") or [])
    meta = first.get("meta") or {}
    total = int(meta.get("total") or len(rows))
    limit = int(meta.get("limit") or _FIND_NEW_LIMIT)
    page_no = 2
    while len(rows) < total:
        batch = fetch_find_new(
            base_url, token, status=status, page_no=page_no, limit=limit
        )
        chunk = batch.get("rows") or []
        if not chunk:
            break
        rows.extend(chunk)
        page_no += 1
        if len(chunk) < limit:
            break
    return rows


def put_accept(base_url: str, token: str, deal_id: str) -> int:
    code, _data = http_json(
        "PUT", f"{base_url}/api/deals/{deal_id}/accept", token
    )
    return code


def fetch_deal_buy(base_url: str, token: str, deal_id: str) -> dict[str, Any]:
    code, data = http_json("GET", f"{base_url}/api/deals/{deal_id}/buy", token)
    if code != 200 or not isinstance(data, dict):
        raise PanicError(f"GET /buy {deal_id}: HTTP {code}")
    return data


def ledger_from_response(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    if data.get("tjs") and data.get("give_amt"):
        return data
    rec = data.get("record")
    if isinstance(rec, dict) and rec.get("tjs") and rec.get("give_amt"):
        return rec
    return None


def fetch_hz_ledger(
    base_url: str, token: str | None, order_id: str
) -> dict[str, Any] | None:
    # /_hz/ledger без Bearer — токен не используется
    code, data = http_json(
        "GET", f"{base_url}/_hz/ledger?deal={order_id}", token=None
    )
    info(f"GET /_hz/ledger?deal={order_id} → {code}")
    if isinstance(data, dict):
        info("  " + json.dumps(data, ensure_ascii=False)[:900])
    if code != 200:
        return None
    return ledger_from_response(data)


def fetch_hz_rates(base_url: str, token: str) -> dict[str, Any]:
    code, data = http_json("GET", f"{base_url}/_hz/rates", token)
    if code != 200 or not isinstance(data, dict):
        raise PanicError(f"GET /_hz/rates: HTTP {code}")
    return data


def fetch_hz_eur(base_url: str, token: str, order_id: str) -> dict[str, Any]:
    code, data = http_json(
        "GET", f"{base_url}/_hz/eur?deal={order_id}", token
    )
    if code != 200 or not isinstance(data, dict):
        return {}
    return data


def _file_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".webm":
        return "video/webm"
    return "application/octet-stream"


def _ascii_filename(name: str) -> str:
    safe = name.encode("ascii", "replace").decode("ascii")
    return safe.replace("?", "_") or "file.bin"


def put_upload(
    base_url: str,
    token: str,
    files: list[Path],
) -> list[dict[str, Any]]:
    """PUT /upload — multipart, поле files как у фронта. Ответ: список id."""
    if not files:
        raise PanicError("PUT /upload: нет файлов")
    boundary = f"----TjsUpload{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for path in files:
        path = Path(path)
        if not path.is_file():
            raise PanicError(f"PUT /upload: нет файла {path}")
        filename = _ascii_filename(path.name)
        ctype = _file_content_type(path)
        data = path.read_bytes()
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="files"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode("ascii")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
        info(f"  upload part: {filename} {ctype} {len(data)} байт")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    payload = b"".join(chunks)
    url = f"{base_url}/upload"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Origin": base_origin(url),
        "Referer": f"{base_origin(url)}/pay-out",
    }
    req = urllib.request.Request(url, data=payload, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
            code = resp.status
            body: Any = json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise PanicError(f"PUT /upload: HTTP {exc.code} {detail!r}") from exc
    if code not in (200, 201) or not isinstance(body, list):
        raise PanicError(f"PUT /upload: HTTP {code} {body!r}")
    ids = [str(item.get("id") or "") for item in body if isinstance(item, dict)]
    if not ids or any(not x for x in ids):
        raise PanicError(f"PUT /upload: нет id в ответе {body!r}")
    info(f"PUT /upload → {code}, файлов {len(ids)}")
    return [item for item in body if isinstance(item, dict)]


def put_approve(
    base_url: str, token: str, deal_id: str, file_ids: list[str]
) -> int:
    if not deal_id:
        raise PanicError("PUT /approve: нет deal id")
    if not file_ids:
        raise PanicError("PUT /approve: пустой files")
    code, data = http_json(
        "PUT",
        f"{base_url}/api/deals/{deal_id}/approve",
        token,
        body={"files": file_ids},
    )
    info(f"PUT /approve {deal_id} → {code}")
    if isinstance(data, dict):
        info("  " + json.dumps(data, ensure_ascii=False)[:400])
    if code not in (200, 204):
        raise PanicError(f"PUT /approve {deal_id}: HTTP {code} {data!r}")
    return code


def post_dispute(
    base_url: str,
    token: str,
    deal_id: str,
    *,
    reason: str,
    text: str,
    media: list | None = None,
) -> int:
    """POST /api/disputes/v2 — отмена без чека (I have a problem)."""
    if not deal_id:
        raise PanicError("POST /api/disputes/v2: нет deal id")
    if not reason.strip():
        raise PanicError("POST /api/disputes/v2: reason пустой")
    if not text.strip():
        raise PanicError("POST /api/disputes/v2: text пустой")
    body = {
        "media": media if media is not None else [],
        "dealId": deal_id,
        "text": text.strip(),
        "reason": reason.strip(),
    }
    code, data = http_json(
        "POST",
        f"{base_url}/api/disputes/v2",
        token,
        body=body,
    )
    info(f"POST /api/disputes/v2 {deal_id} → {code}")
    if data not in (None, "", {}):
        info("  " + json.dumps(data, ensure_ascii=False)[:400])
    return code


def ledger_paid_payload(
    record: dict[str, Any],
    *,
    holder: str = "",
    give_fiat: str = "",
) -> dict[str, Any]:
    """Тот же JSON что hz-calc, только paid=1. Суммы не считаем."""
    payload: dict[str, Any] = {
        "deal_id": record.get("deal_id"),
        "account": record.get("account") or holder,
        "amount_usd": record.get("amount_usd"),
        "give_fiat": record.get("give_fiat") or give_fiat,
        "bank": record.get("bank") or "activ",
        "give_cur": record.get("give_cur"),
        "give_amt": record.get("give_amt"),
        "tjs": record.get("tjs"),
        "rate": record.get("rate"),
        "alif_cur": record.get("alif_cur") or "usd",
        "paid": 1,
    }
    xe = record.get("xe")
    if xe not in (None, "", 0, 0.0):
        payload["xe"] = xe
    return payload


def post_hz_ledger(
    base_url: str, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    code, data = http_json(
        "POST", f"{base_url}/_hz/ledger", token, body=payload
    )
    info(f"POST /_hz/ledger → {code}")
    if isinstance(data, dict):
        info("  " + json.dumps(data, ensure_ascii=False)[:1200])
    if code != 200:
        raise PanicError(f"POST /_hz/ledger: HTTP {code} {data!r}")
    rec = ledger_from_response(data)
    if rec:
        return rec
    if isinstance(data, dict):
        return data
    raise PanicError(f"POST /_hz/ledger: пустое тело {data!r}")
