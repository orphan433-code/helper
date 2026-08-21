"""PlatCore + hz HTTP через fetch в уже открытой вкладке (те же cookies)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page

from core.validators import PanicError

_FIND_NEW_TYPE = "buyAll"
_FIND_NEW_LIMIT = 100


def origin_from_page(page: Page) -> str:
    parsed = urlparse(page.url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://hz.temkitemki.work"


async def page_fetch(
    page: Page,
    method: str,
    path: str,
    *,
    body: Any | None = None,
) -> tuple[int, Any]:
    result = await page.evaluate(
        """async ({ method, path, body }) => {
            const headers = {};
            const keys = [
                "token", "accessToken", "access_token",
                "authToken", "jwt", "bearer", "platcore_token",
            ];
            let tok = null;
            for (const k of keys) {
                const v = localStorage.getItem(k) || sessionStorage.getItem(k);
                if (v && v.length > 20) { tok = v; break; }
            }
            if (!tok) {
                for (const store of [localStorage, sessionStorage]) {
                    for (let i = 0; i < store.length; i++) {
                        const k = store.key(i);
                        const v = store.getItem(k);
                        if (!v || v.length < 40) continue;
                        if (v.split(".").length === 3) { tok = v; break; }
                    }
                    if (tok) break;
                }
            }
            if (tok) {
                if (String(tok).toLowerCase().startsWith("bearer ")) {
                    tok = String(tok).slice(7).trim();
                }
                headers["Authorization"] = "Bearer " + tok;
            }
            const opts = { method, credentials: "same-origin", headers };
            if (body !== null && body !== undefined) {
                headers["Content-Type"] = "application/json";
                opts.body = JSON.stringify(body);
            }
            const res = await fetch(path, opts);
            const text = await res.text();
            let data = null;
            if (text) {
                try { data = JSON.parse(text); }
                catch { data = text; }
            }
            return { status: res.status, data };
        }""",
        {"method": method, "path": path, "body": body},
    )
    if not isinstance(result, dict):
        raise PanicError(f"fetch {method} {path}: пустой ответ")
    return int(result.get("status") or 0), result.get("data")


async def fetch_find_new(
    page: Page,
    *,
    status: str = "new",
    page_no: int = 1,
    limit: int = _FIND_NEW_LIMIT,
) -> dict[str, Any]:
    path = (
        f"/api/deals/findNew?page={page_no}&limit={limit}"
        f"&status={status}&type={_FIND_NEW_TYPE}"
    )
    code, data = await page_fetch(page, "GET", path)
    if code != 200 or not isinstance(data, dict):
        raise PanicError(f"findNew {status}: HTTP {code}")
    return data


async def fetch_find_new_rows(
    page: Page,
    *,
    status: str = "new",
) -> list[dict[str, Any]]:
    first = await fetch_find_new(page, status=status, page_no=1)
    rows = list(first.get("rows") or [])
    meta = first.get("meta") or {}
    total = int(meta.get("total") or len(rows))
    limit = int(meta.get("limit") or _FIND_NEW_LIMIT)
    page_no = 2
    while len(rows) < total:
        batch = await fetch_find_new(page, status=status, page_no=page_no, limit=limit)
        chunk = batch.get("rows") or []
        if not chunk:
            break
        rows.extend(chunk)
        page_no += 1
        if len(chunk) < limit:
            break
    return rows


async def put_accept(page: Page, deal_id: str) -> int:
    code, _data = await page_fetch(page, "PUT", f"/api/deals/{deal_id}/accept")
    return code


async def fetch_deal_buy(page: Page, deal_id: str) -> dict[str, Any]:
    code, data = await page_fetch(page, "GET", f"/api/deals/{deal_id}/buy")
    if code != 200 or not isinstance(data, dict):
        raise PanicError(f"GET /buy {deal_id}: HTTP {code}")
    return data


async def fetch_hz_ledger(page: Page, order_id: str) -> dict[str, Any] | None:
    code, data = await page_fetch(
        page, "GET", f"/_hz/ledger?deal={order_id}"
    )
    if code != 200:
        return None
    if isinstance(data, dict):
        rec = data.get("record")
        return rec if isinstance(rec, dict) else None
    return None
