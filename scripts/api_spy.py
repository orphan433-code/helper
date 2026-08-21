#!/usr/bin/env python3
"""
Сниффер API PlatCore. Пишет логи сюда, не в консоль браузера.

  .venv/bin/python scripts/api_spy.py
  .venv/bin/python scripts/api_spy.py --pending --har

Бот с тем же профилем должен быть закрыт (кроме --cdp).
Кликай Accept / Approve / грузи чеки. Ctrl+C — сводка.

Логи: runtime/api_spy/<stamp>/
  events.jsonl     все запросы
  notable.jsonl    accept / ledger POST / upload / approve / canvas / formdata
  summary.md       читаемая лента
  bodies/          JSON-тела
  findNew_*.json   снимок списка на старте
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from playwright.async_api import Response, async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SKIP_EXT = (
    ".js",
    ".css",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".svg",
)
_STATIC_TYPES = frozenset(
    {"stylesheet", "script", "font", "image", "media", "manifest"}
)
_INTERESTING_TYPES = frozenset({"xhr", "fetch", "document"})
_BODY_MAX = 400_000
_TEXT_PART_MAX = 8_192
_REDACT_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-auth-token",
        "x-access-token",
    }
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
_INTERESTING_PATH = re.compile(
    r"/api/"
    r"|accept|approve|upload|proof|receipt|document|file"
    r"|rate|course|xe|fx|currency|quote|calc"
    r"|deal|pay-out|findNew|multipart|_hz/",
    re.I,
)
_POLL_PATHS = frozenset(
    {
        "/_hz/rates",
        "/_hz/ledger",
        "/api/disputes/v2/disputes-summary",
        "/api/deals/findNew",
        "/api/wallets",
        "/api/counter",
        "/api/traders/v2/online-global",
    }
)
_NOTABLE_RE = re.compile(
    r"/upload|/approve|/accept|/buy\b|/info\b|/ledger|/eur\b|/disputes/v2$",
    re.I,
)

_HOOK_JS = r"""
(() => {
  if (window.__tjsSpyHooked) return;
  window.__tjsSpyHooked = true;
  const push = (payload) => {
    try {
      if (typeof window.tjsSpy === "function") window.tjsSpy(payload);
    } catch (e) {}
  };

  const formParts = (fd) => {
    const parts = [];
    for (const [name, value] of fd.entries()) {
      if (typeof Blob !== "undefined" && value instanceof Blob) {
        parts.push({
          name,
          filename: value.name || null,
          content_type: value.type || null,
          bytes: value.size,
          is_file: true,
        });
      } else {
        const text = String(value);
        parts.push({
          name,
          text: text.length > 4000 ? text.slice(0, 4000) : text,
          bytes: text.length,
          is_file: false,
        });
      }
    }
    return parts;
  };

  const inspectBody = (body) => {
    if (body == null) return null;
    if (typeof FormData !== "undefined" && body instanceof FormData) {
      return { kind: "formdata", multipart: formParts(body) };
    }
    if (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) {
      return { kind: "params", text: body.toString() };
    }
    if (typeof Blob !== "undefined" && body instanceof Blob) {
      return {
        kind: "blob",
        content_type: body.type || null,
        bytes: body.size,
        filename: body.name || null,
      };
    }
    if (typeof body === "string") {
      try { return { kind: "json", json: JSON.parse(body) }; }
      catch { return { kind: "text", text: body.slice(0, 8000) }; }
    }
    return { kind: typeof body };
  };

  const interestingUrl = (url) =>
    /\/upload|\/approve|\/accept|\/ledger|\/eur|_hz|\/deals\//i.test(String(url || ""));

  const origFetch = window.fetch;
  window.fetch = async function (input, init) {
    try {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      const method = String(
        (init && init.method) || (input && input.method) || "GET"
      ).toUpperCase();
      const inspected = inspectBody(init && init.body);
      const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
      if (
        (inspected && inspected.kind === "formdata") ||
        (mutating && (interestingUrl(url) || inspected))
      ) {
        push({ src: "fetch", method, url, body: inspected });
      }
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };

  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__tjsMethod = method;
    this.__tjsUrl = String(url);
    return origOpen.apply(this, arguments);
  };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) {
    try {
      const method = String(this.__tjsMethod || "POST").toUpperCase();
      const url = this.__tjsUrl || "";
      const inspected = inspectBody(body);
      const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
      if (
        (inspected && inspected.kind === "formdata") ||
        (mutating && (interestingUrl(url) || inspected))
      ) {
        push({ src: "xhr", method, url, body: inspected });
      }
    } catch (e) {}
    return origSend.apply(this, arguments);
  };

  const hookCanvas = (name) => {
    const orig = HTMLCanvasElement.prototype[name];
    if (!orig) return;
    HTMLCanvasElement.prototype[name] = function (...args) {
      try {
        if (name === "toBlob") {
          const cb = args[0];
          args[0] = function (blob) {
            try {
              push({
                src: "canvas",
                method: "toBlob",
                url: location.href,
                w: this.width,
                h: this.height,
                bytes: blob && blob.size,
                type: blob && blob.type,
              });
            } catch (e) {}
            if (typeof cb === "function") cb(blob);
          }.bind(this);
          return orig.apply(this, args);
        }
        push({
          src: "canvas",
          method: name,
          url: location.href,
          w: this.width,
          h: this.height,
        });
      } catch (e) {}
      return orig.apply(this, args);
    };
  };
  if (window.HTMLCanvasElement) {
    hookCanvas("toBlob");
    hookCanvas("toDataURL");
  }
})();
"""


def load_config() -> dict:
    path = ROOT / "config.yaml"
    example = ROOT / "config.example.yaml"
    if not path.is_file() and example.is_file():
        path.write_bytes(example.read_bytes())
    if not path.is_file():
        raise SystemExit(f"Нет config.yaml: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Битый config.yaml: {path}")
    return data


def _api_base_url(cfg: dict) -> str:
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


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _redact(value: str) -> str:
    text = str(value or "")
    if len(text) <= 12:
        return "***"
    return f"{text[:6]}…{text[-6:]} (len={len(text)})"


def _headers(raw: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if key.lower() in _REDACT_HEADERS:
            out[key] = _redact(value)
        else:
            out[key] = value
    return out


def _safe_name(url: str, method: str, seq: int) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "root"
    path = re.sub(r"[^A-Za-z0-9._-]", "_", path)[:80]
    return f"{seq:03d}_{method}_{path}"


def _looks_json(raw: bytes) -> bool:
    stripped = raw.lstrip()
    return stripped[:1] in (b"{", b"[")


def _decode_body(raw: bytes | None, content_type: str) -> Any:
    if raw is None:
        return None
    if not raw:
        return ""
    ctype = (content_type or "").lower()
    if "octet-stream" in ctype or "image/" in ctype or "video/" in ctype:
        return {"binary": True, "content_type": content_type, "bytes": len(raw)}
    if len(raw) > _BODY_MAX:
        head = raw[:2000].decode("utf-8", errors="replace")
        return {
            "truncated": True,
            "bytes": len(raw),
            "head": head,
        }
    if "json" in ctype or _looks_json(raw):
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if "multipart/form-data" in ctype:
        return {"multipart": _parse_multipart(raw, content_type)}
    text = raw.decode("utf-8", errors="replace")
    if len(text) > 20_000:
        return {"truncated": True, "bytes": len(raw), "head": text[:2000]}
    return text


def _parse_multipart(body: bytes, content_type: str) -> list[dict[str, Any]]:
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type, re.I)
    if not match:
        return [{"error": "no-boundary", "bytes": len(body)}]
    boundary = (match.group(1) or match.group(2)).strip().encode("ascii", "ignore")
    if not boundary:
        return [{"error": "empty-boundary", "bytes": len(body)}]
    parts: list[dict[str, Any]] = []
    for chunk in body.split(b"--" + boundary):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, _, payload = chunk.partition(b"\r\n\r\n")
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        headers_txt = header_blob.decode("utf-8", errors="replace")
        name = ""
        filename = ""
        part_type = ""
        for line in headers_txt.split("\r\n"):
            lower = line.lower()
            if lower.startswith("content-disposition:"):
                disp = line.split(":", 1)[1].strip()
                name_m = re.search(r'name="([^"]*)"', disp)
                file_m = re.search(r'filename="([^"]*)"', disp)
                name = name_m.group(1) if name_m else ""
                filename = file_m.group(1) if file_m else ""
            elif lower.startswith("content-type:"):
                part_type = line.split(":", 1)[1].strip()
        item: dict[str, Any] = {
            "name": name,
            "filename": filename or None,
            "content_type": part_type or None,
            "bytes": len(payload),
        }
        sniff = (part_type or "").lower()
        is_text = (
            "json" in sniff
            or sniff.startswith("text/")
            or (not filename and not sniff.startswith("image/"))
        )
        if is_text and len(payload) <= _TEXT_PART_MAX:
            if _looks_json(payload) or "json" in sniff:
                try:
                    item["json"] = json.loads(payload.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    item["text"] = payload.decode("utf-8", errors="replace")
            else:
                item["text"] = payload.decode("utf-8", errors="replace")
        elif filename:
            item["note"] = "binary-omitted"
        parts.append(item)
    return parts


def _interesting(url: str, resource_type: str, *, capture_all: bool) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.startswith("/ws/") or resource_type == "websocket":
        return False
    if capture_all:
        return True
    if any(path.endswith(ext) for ext in _SKIP_EXT):
        return False
    if resource_type in _STATIC_TYPES:
        return False
    if resource_type in _INTERESTING_TYPES:
        return True
    if _INTERESTING_PATH.search(url):
        return True
    return False


def _is_notable(rec: dict[str, Any]) -> bool:
    if rec.get("hook_src") in ("canvas",) or rec.get("resource_type") == "hook":
        body = rec.get("req_body")
        if isinstance(body, dict) and body.get("kind") == "formdata":
            return True
        if rec.get("hook_src") == "canvas":
            return True
        method = str(rec.get("method") or "").upper()
        if method in ("PUT", "POST", "PATCH"):
            return True
    url = rec.get("url") or ""
    method = str(rec.get("method") or "").upper()
    path = urlparse(url).path
    if method in ("PUT", "POST", "PATCH", "DELETE"):
        return True
    if _NOTABLE_RE.search(path):
        return True
    return False


def _one_line(rec: dict[str, Any]) -> str:
    status = rec.get("status")
    st = "-" if status is None else str(status)
    url = rec.get("url") or ""
    parsed = urlparse(url)
    short = parsed.path or "/"
    if parsed.query:
        q = parsed.query
        if len(q) > 80:
            q = q[:80] + "…"
        short = f"{short}?{q}"
    extra = ""
    body = rec.get("req_body")
    parts = None
    if isinstance(body, dict) and "multipart" in body:
        parts = body.get("multipart")
    if rec.get("hook_src"):
        extra += f" hook={rec.get('hook_src')}"
    if isinstance(parts, list):
        files = []
        for part in parts:
            name = part.get("filename") or part.get("name") or "?"
            size = part.get("bytes")
            files.append(f"{name}:{size}b")
        extra += " files=[" + ", ".join(files) + "]"
    canvas = rec.get("canvas")
    if isinstance(canvas, dict) and canvas.get("w"):
        extra += f" canvas={canvas.get('w')}x{canvas.get('h')}"
        if canvas.get("bytes"):
            extra += f":{canvas.get('bytes')}b"
    return (
        f"{rec.get('t', '')}  {rec.get('method', '?')} {st}  "
        f"{short}{extra}"
    )


class SpyLog:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.bodies = out_dir / "bodies"
        self.events_path = out_dir / "events.jsonl"
        self.notable_path = out_dir / "notable.jsonl"
        self.summary_path = out_dir / "summary.md"
        self.bodies.mkdir(parents=True, exist_ok=True)
        self.seq = 0
        self.skipped_polls = 0
        self.rows: list[str] = []
        self.lock = asyncio.Lock()
        self._poll_seen: dict[str, str] = {}
        self.events_path.write_text("", encoding="utf-8")
        self.notable_path.write_text("", encoding="utf-8")
        self._write_summary()

    def _write_summary(self) -> None:
        lines = [
            f"# API spy {self.out_dir.name}",
            "",
            f"Всего: {self.seq}  (поллы скрыты: {self.skipped_polls})",
            "",
            "```",
            *self.rows,
            "```",
            "",
        ]
        self.summary_path.write_text("\n".join(lines), encoding="utf-8")

    def _dup_poll(self, rec: dict[str, Any]) -> bool:
        if rec.get("resource_type") == "hook":
            return False
        method = str(rec.get("method") or "")
        if method != "GET":
            return False
        path = urlparse(rec.get("url") or "").path
        if path not in _POLL_PATHS:
            return False
        key = rec.get("url") or path
        dumped = json.dumps(rec.get("res_body"), sort_keys=True, default=str)
        if self._poll_seen.get(key) == dumped:
            return True
        self._poll_seen[key] = dumped
        return False

    async def write(self, rec: dict[str, Any]) -> None:
        async with self.lock:
            if self._dup_poll(rec):
                self.skipped_polls += 1
                return
            self.seq += 1
            rec["seq"] = self.seq
            line = json.dumps(rec, ensure_ascii=False, default=str)
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if _is_notable(rec):
                with self.notable_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            pretty = _one_line(rec)
            self.rows.append(pretty)
            print(pretty, flush=True)
            self._maybe_dump_body(rec)
            self._write_summary()

    def _maybe_dump_body(self, rec: dict[str, Any]) -> None:
        url = str(rec.get("url") or "")
        method = str(rec.get("method") or "GET")
        name = _safe_name(url, method, rec["seq"])
        dumped = False
        for key in ("req_body", "res_body"):
            body = rec.get(key)
            if isinstance(body, (dict, list)):
                path = self.bodies / f"{name}_{key}.json"
                path.write_text(
                    json.dumps(body, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                dumped = True
        if dumped:
            rec["body_files"] = True


def _pending_url(base_url: str) -> str:
    return f"{base_url}/pay-out?limit=100&status=pending"


def _new_url(base_url: str) -> str:
    return f"{base_url}/pay-out?limit=100&status=new&filter=opened"


async def _read_token(page) -> str | None:
    keys_json = json.dumps(_TOKEN_KEYS)
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
    if not token:
        return None
    text = str(token).strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return text or None


def _http_json(method: str, url: str, token: str) -> Any:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc


def dump_findnew(base_url: str, token: str, out_dir: Path, cfg: dict) -> None:
    decline = cfg.get("bank_decline") or {}
    limit = int(decline.get("find_new_limit", 50))
    deal_type = str(decline.get("find_new_type", "buyAll"))
    for status in ("new", "pending"):
        url = (
            f"{base_url}/api/deals/findNew"
            f"?page=1&limit={limit}&status={status}&type={deal_type}"
        )
        try:
            data = _http_json("GET", url, token)
        except Exception as exc:
            print(f"[findNew {status}] fail: {exc}", flush=True)
            continue
        path = out_dir / f"findNew_{status}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        rows = (data or {}).get("rows") if isinstance(data, dict) else None
        n = len(rows) if isinstance(rows, list) else "?"
        keys: list[str] = []
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            keys = sorted(rows[0].keys())
        print(f"[findNew {status}] {n} rows → {path.name}", flush=True)
        if keys:
            print(f"  keys: {', '.join(keys)}", flush=True)


async def _handle_response(
    response: Response,
    spy: SpyLog,
    *,
    capture_all: bool,
    host_hint: str,
) -> None:
    request = response.request
    url = request.url
    resource_type = request.resource_type
    if not _interesting(url, resource_type, capture_all=capture_all):
        return

    req_ctype = request.headers.get("content-type") or ""
    req_body: Any = None
    try:
        if request.method not in ("GET", "HEAD"):
            buf = request.post_data_buffer
            req_body = _decode_body(buf, req_ctype)
    except Exception:
        req_body = {"error": "req-body-unreadable"}

    res_ctype = ""
    try:
        res_ctype = response.headers.get("content-type") or ""
    except Exception:
        pass
    res_body: Any = None
    try:
        raw = await response.body()
        res_body = _decode_body(raw, res_ctype)
    except Exception:
        res_body = None

    rec: dict[str, Any] = {
        "t": _now_iso(),
        "method": request.method,
        "url": url,
        "host": urlparse(url).netloc,
        "same_host": host_hint in urlparse(url).netloc,
        "resource_type": resource_type,
        "status": response.status,
        "req_headers": _headers(request.headers),
        "req_body": req_body,
        "res_headers": _headers(dict(response.headers)),
        "res_body": res_body,
    }
    await spy.write(rec)


def _attach_page(page, spy: SpyLog, *, capture_all: bool, host_hint: str) -> None:
    def on_response(response: Response) -> None:
        task = asyncio.create_task(
            _handle_response(
                response,
                spy,
                capture_all=capture_all,
                host_hint=host_hint,
            )
        )
        inflight.add(task)
        task.add_done_callback(inflight.discard)

    page.on("response", on_response)


inflight: set[asyncio.Task] = set()


async def _install_hooks(context, spy: SpyLog) -> None:
    async def _on_hook(_source: Any, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        body = payload.get("body")
        rec: dict[str, Any] = {
            "t": _now_iso(),
            "method": str(payload.get("method") or "HOOK"),
            "url": str(payload.get("url") or ""),
            "resource_type": "hook",
            "status": None,
            "req_headers": {},
            "req_body": body,
            "res_headers": {},
            "res_body": None,
            "hook_src": payload.get("src"),
        }
        if payload.get("src") == "canvas":
            rec["canvas"] = {
                "w": payload.get("w"),
                "h": payload.get("h"),
                "bytes": payload.get("bytes"),
                "type": payload.get("type"),
            }
        await spy.write(rec)

    await context.expose_binding("tjsSpy", _on_hook)
    await context.add_init_script(_HOOK_JS)
    for page in context.pages:
        try:
            await page.evaluate(_HOOK_JS)
        except Exception:
            pass

    def _on_page(page) -> None:
        async def _inject() -> None:
            try:
                await page.evaluate(_HOOK_JS)
            except Exception:
                pass

        asyncio.create_task(_inject())

    context.on("page", _on_page)


async def run(args: argparse.Namespace) -> None:
    cfg = load_config()
    base = _api_base_url(cfg)
    host_hint = urlparse(base).netloc
    out_dir = ROOT / "runtime" / "api_spy" / _stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    spy = SpyLog(out_dir)

    print(f"Логи: {out_dir}", flush=True)
    print("Кликай Accept / Approve / грузи чеки. Ctrl+C — стоп.", flush=True)

    browser_cfg = cfg.get("browser") or {}
    profile = (ROOT / browser_cfg.get("user_data_dir", "../CNY/browser_profile")).resolve()
    har_path = out_dir / "session.har" if args.har else None

    async with async_playwright() as p:
        if args.cdp:
            browser = await p.chromium.connect_over_cdp(args.cdp)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
        else:
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile),
                "headless": False,
                "viewport": {"width": 1400, "height": 900},
                "locale": "ru-RU",
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if har_path is not None:
                launch_kwargs["record_har_path"] = str(har_path)
                launch_kwargs["record_har_content"] = "embed"
            try:
                context = await p.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc:
                raise SystemExit(
                    f"Профиль занят или не открылся: {exc}\n"
                    "Закрой бот (тот же browser_profile) или запусти с --cdp."
                ) from exc

        await _install_hooks(context, spy)

        for page in context.pages:
            _attach_page(page, spy, capture_all=args.all, host_hint=host_hint)
        context.on(
            "page",
            lambda page: _attach_page(
                page, spy, capture_all=args.all, host_hint=host_hint
            ),
        )

        page = context.pages[0] if context.pages else await context.new_page()
        start_url = _pending_url(base) if args.pending else _new_url(base)
        await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1500)

        token = await _read_token(page)
        if token:
            dump_findnew(base, token, out_dir, cfg)
        else:
            print("Токен не найден в storage — findNew на старте пропущен", flush=True)

        if args.list_only:
            print("list-only: готово. Смотри findNew_*.json", flush=True)
            await context.close()
            return

        print("Шпион слушает. Не закрывай окно.", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        try:
            await stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if inflight:
                await asyncio.gather(*inflight, return_exceptions=True)
            if not args.cdp:
                try:
                    await context.close()
                except Exception:
                    pass

    print(f"\nСводка:  {spy.summary_path}", flush=True)
    print(f"Важное:  {spy.notable_path}", flush=True)
    print(f"JSONL:   {spy.events_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Сниффер API PlatCore → runtime/api_spy/")
    parser.add_argument("--all", action="store_true", help="Все ресурсы, не только XHR/API")
    parser.add_argument("--har", action="store_true", help="Ещё session.har")
    parser.add_argument("--pending", action="store_true", help="Стартовать со status=pending")
    parser.add_argument("--list-only", action="store_true", help="Только findNew, без слежки")
    parser.add_argument("--cdp", default="", help="Подключиться к уже открытому Chrome")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nСтоп.", flush=True)


if __name__ == "__main__":
    main()
