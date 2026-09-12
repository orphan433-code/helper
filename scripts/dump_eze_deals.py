#!/usr/bin/env python3
"""Снимок EasySend findNew /buy — сравнение полей сумм. Не accept/cancel."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platcore-decline"))

import decline_by_bank_api as dapi  # noqa: E402
from core.decline_hosts import DECLINE_SERVICE_URLS  # noqa: E402
from core.paths import RUNTIME_DIR  # noqa: E402

OUT_DIR = RUNTIME_DIR / "eze_dump"
EZE = DECLINE_SERVICE_URLS["eze"]


def _mask_card(raw: object) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) < 6:
        return "????"
    return f"{digits[:6]}…{digits[-4:]} ({len(digits)})"


def _brand(card: str) -> str:
    if card.startswith("4"):
        return "visa"
    if card.startswith(("2", "5")):
        return "mc"
    return "?"


def _walk_nums(obj: Any, prefix: str, out: list[tuple[str, Any]]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_nums(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        if obj and not isinstance(obj[0], (dict, list)):
            return
        for i, v in enumerate(obj[:3]):
            _walk_nums(v, f"{prefix}[{i}]", out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append((prefix, obj))
    elif isinstance(obj, str):
        text = obj.strip().replace(" ", "").replace(",", ".")
        if text and text.replace(".", "", 1).replace("-", "", 1).isdigit():
            try:
                out.append((prefix, float(text)))
            except ValueError:
                pass


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in {"accountnumber", "account", "card", "pan"} or "card" in kl:
                out[k] = _mask_card(v) if not isinstance(v, (dict, list)) else _sanitize(v)
            elif "token" in kl or "secret" in kl:
                out[k] = "***"
            else:
                out[k] = _sanitize(v)
        return out
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def _probe(base: str, token: str, method: str, path: str) -> dict[str, Any]:
    url = f"{base}{path}"
    try:
        code, data = dapi._http_json(method, url, token)
        return {"ok": True, "code": code, "data": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _row_brief(row: dict[str, Any]) -> dict[str, Any]:
    cred = row.get("credentials") or {}
    card = str(cred.get("accountNumber") or "")
    out = row.get("out") if isinstance(row.get("out"), dict) else {}
    amounts = row.get("amounts") if isinstance(row.get("amounts"), dict) else {}
    bank = row.get("bank") if isinstance(row.get("bank"), dict) else {}
    cur = row.get("currencyTo") if isinstance(row.get("currencyTo"), dict) else {}
    return {
        "orderId": row.get("orderId"),
        "status": row.get("status"),
        "brand": _brand(card),
        "card": _mask_card(card),
        "bank": bank.get("name"),
        "amount": row.get("amount"),
        "currencyTo": cur.get("code") or row.get("currencyTo"),
        "out.trader": out.get("trader"),
        "out.client": out.get("client"),
        "out.bodyFinal": out.get("bodyFinal"),
        "out.body": out.get("body"),
        "amounts": amounts,
        "out_keys": sorted(out.keys()) if out else [],
        "top_keys": sorted(row.keys()),
    }


async def main() -> int:
    cfg = dapi.load_config()
    browser = dict(cfg.get("browser") or {})
    browser["headless"] = True
    cfg["browser"] = browser
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] origin {EZE}", flush=True)
    token = await dapi.resolve_token(cfg, EZE)
    print("[INFO] token ok", flush=True)

    dump: dict[str, Any] = {"origin": EZE, "statuses": {}}

    for status in ("new", "pending"):
        print(f"[INFO] findNew status={status}", flush=True)
        try:
            rows = dapi.fetch_deals_by_status(cfg=cfg, base_url=EZE, token=token, deal_status=status)
        except Exception as exc:
            dump["statuses"][status] = {"error": str(exc)}
            print(f"[ERR] findNew {status}: {exc}", flush=True)
            continue
        briefs = [_row_brief(r) for r in rows if isinstance(r, dict)]
        dump["statuses"][status] = {
            "count": len(rows),
            "briefs": briefs[:25],
        }
        raw_path = OUT_DIR / f"findNew_{status}.json"
        raw_path.write_text(
            json.dumps(_sanitize(rows[:15]), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[OK] {status}: {len(rows)} rows → {raw_path}", flush=True)
        if briefs:
            nums: list[tuple[str, Any]] = []
            _walk_nums(rows[0], "", nums)
            money = [
                (k, v)
                for k, v in nums
                if any(
                    s in k.lower()
                    for s in (
                        "amount",
                        "out.",
                        "fee",
                        "trader",
                        "client",
                        "body",
                        "usd",
                        "eur",
                        "fiat",
                        "rate",
                        "usdt",
                    )
                )
            ]
            print(f"  keys0: {', '.join(briefs[0]['top_keys'])}", flush=True)
            print(f"  money paths: {money[:40]}", flush=True)

    probes = {
        "rates": _probe(EZE, token, "GET", "/_hz/rates"),
        "eur": _probe(EZE, token, "GET", "/_hz/eur?deal=test"),
        "ledger": _probe(EZE, token, "GET", "/_hz/ledger?deal=test"),
    }
    dump["probes"] = {
        k: {
            "ok": v.get("ok"),
            "code": v.get("code"),
            "error": v.get("error"),
            "data_preview": json.dumps(v.get("data"), ensure_ascii=False, default=str)[:400]
            if v.get("ok")
            else None,
        }
        for k, v in probes.items()
    }
    for name, rec in dump["probes"].items():
        print(f"[probe] {name}: {rec}", flush=True)

    # /buy только если уже accepted (pending). Не делаем accept.
    pending = dump.get("statuses", {}).get("pending", {}).get("briefs") or []
    buys: list[dict[str, Any]] = []
    seen_brand: set[str] = set()
    raw_pending = []
    pend_file = OUT_DIR / "findNew_pending.json"
    if pend_file.is_file():
        raw_pending = json.loads(pend_file.read_text(encoding="utf-8"))
    id_by_order = {
        str(r.get("orderId")): str(r.get("_id") or "")
        for r in raw_pending
        if isinstance(r, dict)
    }
    for brief in pending:
        brand = str(brief.get("brand") or "?")
        if brand in seen_brand or brand == "?":
            continue
        deal_id = id_by_order.get(str(brief.get("orderId")) or "")
        if not deal_id:
            continue
        path = f"/api/deals/{deal_id}/buy"
        rec = _probe(EZE, token, "GET", path)
        buys.append(
            {
                "brand": brand,
                "orderId": brief.get("orderId"),
                "probe": {
                    "ok": rec.get("ok"),
                    "code": rec.get("code"),
                    "error": rec.get("error"),
                    "data": _sanitize(rec.get("data")) if rec.get("ok") else None,
                },
            }
        )
        seen_brand.add(brand)
        print(f"[buy] {brand} {brief.get('orderId')}: code={rec.get('code')} err={rec.get('error')}", flush=True)
        if len(seen_brand) >= 2:
            break
    dump["buys"] = buys

    out = OUT_DIR / "analysis.json"
    out.write_text(json.dumps(dump, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[OK] {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(__import__("asyncio").run(main()))
