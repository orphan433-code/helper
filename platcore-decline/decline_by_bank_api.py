#!/usr/bin/env python3
"""
Отмена / редирект сделок через PlatCore API.

  python decline_by_bank_api.py              # dry-run cancel (status=new)
  python decline_by_bank_api.py --execute    # PUT .../cancel
  python decline_by_bank_api.py --redirect --execute
      # PUT .../rematch-friendly-trader {"traderId": "..."}  (new)
  python decline_by_bank_api.py --redirect --deal-status pending --execute
      # то же для pending
  python decline_by_bank_api.py --list
  python decline_by_bank_api.py --debug-token
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent

_DEFAULT_TOKEN_KEYS = (
    "token",
    "accessToken",
    "access_token",
    "authToken",
    "jwt",
    "bearer",
    "platcore_token",
)


def load_config() -> dict:
    path = ROOT / "config.yaml"
    example = ROOT / "config.example.yaml"
    if not path.is_file() and example.is_file():
        path.write_bytes(example.read_bytes())
        print(f"[INFO] Создан {path.name} из config.example.yaml — поправь traders / browser profile")
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
    monitor = str(cfg.get("dashboard", {}).get("monitor_url") or "").strip()
    if monitor:
        parsed = urlparse(monitor)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return "https://hz.temkitemki.work"


def _decline_patterns(cfg: dict) -> list[str]:
    decline = cfg.get("bank_decline") or {}
    raw = decline.get("patterns") or ["tbc"]
    return [str(p).strip().lower() for p in raw if str(p).strip()]


# Пресеты банков для отмены (UI: TBC / Bank of Georgia)
_BANK_PRESETS: dict[str, dict[str, Any]] = {
    "tbc": {
        "label": "TBC",
        "patterns": ["tbc"],
        "card_prefixes": [],
    },
    "bog": {
        "label": "Bank of Georgia",
        "patterns": ["bank of georgia", "georgia", "bog"],
        "card_prefixes": ["548888"],
    },
}


def _normalize_bank_preset(raw: str | None) -> str:
    key = str(raw or "tbc").strip().lower()
    aliases = {
        "tbc": "tbc",
        "bog": "bog",
        "georgia": "bog",
        "bank of georgia": "bog",
        "bank_of_georgia": "bog",
    }
    return aliases.get(key, key if key in _BANK_PRESETS else "tbc")


def _decline_match_rules(
    cfg: dict, *, bank_preset: str | None = None
) -> tuple[list[str], list[str], str]:
    """patterns, card_prefixes, label для фильтра отмены."""
    decline = cfg.get("bank_decline") or {}
    preset_key = _normalize_bank_preset(
        bank_preset or decline.get("default_bank") or "tbc"
    )
    presets_cfg = decline.get("presets") or {}
    preset = dict(_BANK_PRESETS.get(preset_key) or _BANK_PRESETS["tbc"])
    override = presets_cfg.get(preset_key) if isinstance(presets_cfg, dict) else None
    if isinstance(override, dict):
        if override.get("patterns") is not None:
            preset["patterns"] = override.get("patterns")
        if override.get("card_prefixes") is not None:
            preset["card_prefixes"] = override.get("card_prefixes")
        if override.get("label"):
            preset["label"] = override.get("label")
    # legacy: без пресета bog — старые patterns из корня
    if preset_key == "tbc" and not (
        isinstance(override, dict) and override.get("patterns") is not None
    ):
        root_patterns = _decline_patterns(cfg)
        if root_patterns:
            preset["patterns"] = root_patterns
    patterns = [
        str(p).strip().lower()
        for p in (preset.get("patterns") or [])
        if str(p).strip()
    ]
    prefixes = [
        "".join(ch for ch in str(p) if ch.isdigit())
        for p in (preset.get("card_prefixes") or [])
        if str(p).strip()
    ]
    prefixes = [p for p in prefixes if p]
    label = str(preset.get("label") or preset_key)
    return patterns, prefixes, label


def _token_keys(cfg: dict) -> tuple[str, ...]:
    decline = cfg.get("bank_decline") or {}
    keys = decline.get("local_storage_keys")
    if keys:
        return tuple(str(k) for k in keys)
    return _DEFAULT_TOKEN_KEYS


def recipient_bank_name(row: dict[str, Any]) -> str | None:
    creds = row.get("credentials") or {}
    info = creds.get("additionalBankInfo") or {}
    bank = info.get("bank")
    if bank:
        return str(bank).strip()
    return None


def account_digits(row: dict[str, Any]) -> str:
    creds = row.get("credentials") or {}
    raw = str(creds.get("accountNumber") or "")
    return "".join(ch for ch in raw if ch.isdigit())


def is_visa_card(row: dict[str, Any]) -> bool:
    """Visa: номер начинается с 4."""
    digits = account_digits(row)
    return bool(digits) and digits.startswith("4")


def bank_matches(name: str | None, patterns: list[str]) -> bool:
    if not name or not patterns:
        return False
    low = name.lower()
    return any(p in low for p in patterns)


def card_prefix_matches(digits: str, prefixes: list[str]) -> bool:
    if not digits or not prefixes:
        return False
    return any(digits.startswith(p) for p in prefixes)


def deal_matches_bank(
    row: dict[str, Any],
    *,
    patterns: list[str],
    card_prefixes: list[str],
) -> bool:
    """Банк по имени и/или BIN карты (например 548888 = BOG)."""
    if card_prefix_matches(account_digits(row), card_prefixes):
        return True
    return bank_matches(recipient_bank_name(row), patterns)


def _redirect_skip_rules(cfg: dict) -> tuple[list[str], list[str]]:
    """Что НЕ редиректить: BIN + имя банка (Bank of Georgia / 548888)."""
    red = cfg.get("bank_redirect") or {}
    prefixes = [
        "".join(ch for ch in str(p) if ch.isdigit())
        for p in (red.get("skip_card_prefixes") or ["548888"])
        if str(p).strip()
    ]
    prefixes = [p for p in prefixes if p]
    patterns = [
        str(p).strip().lower()
        for p in (
            red.get("skip_bank_patterns")
            or ["bank of georgia", "georgia", "bog"]
        )
        if str(p).strip()
    ]
    return prefixes, patterns


def should_skip_redirect(row: dict[str, Any], cfg: dict) -> bool:
    prefixes, patterns = _redirect_skip_rules(cfg)
    return deal_matches_bank(row, patterns=patterns, card_prefixes=prefixes)


def _strip_bearer(raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


async def _read_token_from_browser(cfg: dict, base_url: str) -> str | None:
    browser_cfg = cfg.get("browser") or {}
    profile = (ROOT / browser_cfg.get("user_data_dir", "../CNY/browser_profile")).resolve()
    keys = list(_token_keys(cfg))
    keys_json = json.dumps(keys)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=bool(browser_cfg.get("headless", True)),
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
            await page.wait_for_timeout(1500)

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


async def debug_storage_keys(cfg: dict, base_url: str) -> None:
    browser_cfg = cfg.get("browser") or {}
    profile = (ROOT / browser_cfg.get("user_data_dir", "../CNY/browser_profile")).resolve()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(f"{base_url}/pay-out?status=new", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            dump = await page.evaluate(
                """() => {
                    const out = { localStorage: {}, sessionStorage: {} };
                    for (const store of [localStorage, sessionStorage]) {
                        const name = store === localStorage ? 'localStorage' : 'sessionStorage';
                        for (let i = 0; i < store.length; i++) {
                            const k = store.key(i);
                            let v = store.getItem(k) || '';
                            if (v.length > 80) v = v.slice(0, 40) + '…' + v.slice(-12);
                            out[name][k] = v;
                        }
                    }
                    return out;
                }"""
            )
            print(json.dumps(dump, ensure_ascii=False, indent=2))
        finally:
            await context.close()


async def resolve_token(cfg: dict, base_url: str) -> str:
    decline = cfg.get("bank_decline") or {}
    for key in (
        decline.get("token"),
        os.environ.get(decline.get("token_env") or "PLATCORE_TOKEN"),
        os.environ.get("PLATCORE_TOKEN"),
    ):
        if key and str(key).strip():
            return _strip_bearer(str(key))

    token = await _read_token_from_browser(cfg, base_url)
    if token:
        return token
    raise SystemExit(
        "Не найден Bearer-токен. Задайте PLATCORE_TOKEN, bank_decline.token в config.yaml "
        "или залогиньтесь в browser_profile и повторите."
    )


def _http_json(
    method: str,
    url: str,
    token: str,
    *,
    body: dict | None = None,
) -> tuple[int, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
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
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc


def fetch_deals_by_status(
    base_url: str,
    token: str,
    cfg: dict,
    *,
    deal_status: str = "new",
) -> list[dict[str, Any]]:
    decline = cfg.get("bank_decline") or {}
    limit = int(decline.get("find_new_limit", 50))
    deal_type = str(decline.get("find_new_type", "buyAll"))
    status_q = str(deal_status or "new").strip().lower() or "new"
    rows: list[dict[str, Any]] = []
    page = 1

    while True:
        url = (
            f"{base_url}/api/deals/findNew"
            f"?page={page}&limit={limit}&status={status_q}&type={deal_type}"
        )
        status, data = _http_json("GET", url, token)
        if status != 200 or not isinstance(data, dict):
            raise RuntimeError(f"findNew: неожиданный ответ {status!r}")

        batch = data.get("rows") or []
        if not isinstance(batch, list):
            break
        rows.extend(batch)

        meta = data.get("meta") or {}
        total = int(meta.get("total") or 0)
        if len(rows) >= total or len(batch) < limit:
            break
        page += 1

    return rows


def fetch_all_new_deals(base_url: str, token: str, cfg: dict) -> list[dict[str, Any]]:
    return fetch_deals_by_status(base_url, token, cfg, deal_status="new")


def cancel_deal(base_url: str, token: str, deal_id: str) -> tuple[int, Any]:
    url = f"{base_url}/api/deals/{deal_id}/cancel"
    return _http_json("PUT", url, token)


def redirect_deal(
    base_url: str, token: str, deal_id: str, trader_id: str
) -> tuple[int, Any]:
    url = f"{base_url}/api/deals/{deal_id}/rematch-friendly-trader"
    return _http_json("PUT", url, token, body={"traderId": trader_id})


def _redirect_cfg(cfg: dict) -> dict:
    return cfg.get("bank_redirect") or {}


def _redirect_traders(cfg: dict) -> list[tuple[str, str]]:
    """Список (label, traderId) из bank_redirect.traders или legacy trader_ids."""
    red = _redirect_cfg(cfg)
    out: list[tuple[str, str]] = []
    for item in red.get("traders") or []:
        if isinstance(item, dict):
            tid = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip() or (tid[:8] if tid else "")
            if tid:
                out.append((label, tid))
        else:
            tid = str(item or "").strip()
            if tid:
                out.append((tid[:8], tid))
    if out:
        return out
    for item in red.get("trader_ids") or []:
        tid = str(item or "").strip()
        if tid:
            out.append((tid[:8], tid))
    return out


def _resolve_active_traders(
    cfg: dict,
    *,
    cli_ids: list[str] | None = None,
    cli_labels: list[str] | None = None,
) -> list[tuple[str, str]]:
    """
    Активные аккаунты для редиректа.
    CLI --trader-id / --trader-label ограничивают список; иначе все из config.
    """
    all_traders = _redirect_traders(cfg)
    by_id = {tid: label for label, tid in all_traders}
    by_label = {label.lower(): (label, tid) for label, tid in all_traders}

    selected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for raw in cli_ids or []:
        tid = str(raw or "").strip()
        if not tid or tid in seen:
            continue
        label = by_id.get(tid, tid[:8])
        selected.append((label, tid))
        seen.add(tid)

    for raw in cli_labels or []:
        key = str(raw or "").strip().lower()
        if not key or key not in by_label:
            raise SystemExit(
                f"Неизвестный аккаунт {raw!r}. "
                f"Доступны: {', '.join(l for l, _ in all_traders)}"
            )
        label, tid = by_label[key]
        if tid not in seen:
            selected.append((label, tid))
            seen.add(tid)

    if selected:
        return selected
    if all_traders:
        return all_traders
    raise SystemExit(
        "bank_redirect.traders пустой — добавь label/id в config.yaml"
    )


def _pick_trader(
    traders: list[tuple[str, str]], *, index: int
) -> tuple[str, str]:
    """Равномерно: 0→A, 1→B, 2→A… Один в списке — всегда он."""
    if not traders:
        raise RuntimeError("нет traderId для редиректа")
    return traders[index % len(traders)]


def _deal_amount(row: dict[str, Any]) -> float | None:
    """Сумма сделки (обычно USDT) из findNew."""
    raw = row.get("amount")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _amount_in_range(
    amount: float | None,
    *,
    min_amount: float | None,
    max_amount: float | None,
) -> bool:
    if min_amount is None and max_amount is None:
        return True
    if amount is None:
        return False
    if min_amount is not None and amount < min_amount:
        return False
    if max_amount is not None and amount > max_amount:
        return False
    return True


def _deal_summary(row: dict[str, Any]) -> str:
    order_id = row.get("orderId") or "?"
    amount = row.get("amount")
    bank = recipient_bank_name(row) or "—"
    owner = (row.get("credentials") or {}).get("ownerName") or ""
    card = (row.get("credentials") or {}).get("accountNumber") or ""
    return (
        f"orderId={order_id} amount={amount} bank={bank!r} "
        f"owner={owner!r} card=…{str(card)[-4:] if card else '?'}"
    )


def _deal_ui_row(row: dict[str, Any], *, ok: bool, error: str = "") -> dict[str, Any]:
    creds = row.get("credentials") or {}
    card = str(creds.get("accountNumber") or "")
    last4 = card[-4:] if len(card) >= 4 else (card or "????")
    amount = row.get("amount")
    return {
        "order_id": str(row.get("orderId") or ""),
        "card": f"*{last4}" if last4 != "????" else "????",
        "holder": str(creds.get("ownerName") or "").strip(),
        "amount": "" if amount is None else str(amount),
        "bank": recipient_bank_name(row) or "",
        "ok": bool(ok),
        "error": (error or "").strip(),
    }


def _emit_ui_result(payload: dict[str, Any]) -> None:
    """Строка для GUI Tzk — не трогать формат префикса."""
    print("TZK_DECLINE_RESULT\t" + json.dumps(payload, ensure_ascii=False))


async def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    base_url = _api_base_url(cfg)
    do_redirect = bool(getattr(args, "redirect", False))
    action = "redirect" if do_redirect else "cancel"
    deal_status = str(getattr(args, "deal_status", None) or "new").strip().lower()
    if deal_status not in ("new", "pending"):
        raise SystemExit(f"Неизвестный --deal-status: {deal_status!r} (new|pending)")
    traders: list[tuple[str, str]] = []
    max_per_run = 0
    min_amt: float | None = None
    max_amt: float | None = None
    bank_preset = _normalize_bank_preset(getattr(args, "bank", None))
    patterns, card_prefixes, bank_label = _decline_match_rules(
        cfg, bank_preset=bank_preset
    )
    skip_prefixes, skip_bank_patterns = _redirect_skip_rules(cfg)
    # По умолчанию все подряд; --skip-bog — не редиректить BOG/548888
    skip_bog = bool(do_redirect and getattr(args, "skip_bog", False))
    # --visa-only — редиректить только карты Visa (4…)
    visa_only = bool(do_redirect and getattr(args, "visa_only", False))

    if do_redirect:
        red = _redirect_cfg(cfg)
        traders = _resolve_active_traders(
            cfg,
            cli_ids=list(getattr(args, "trader_ids", None) or []),
            cli_labels=list(getattr(args, "trader_labels", None) or []),
        )
        max_per_run = int(
            getattr(args, "max_per_run", None)
            if getattr(args, "max_per_run", None) is not None
            else (red.get("max_per_run") or 0)
        )
        min_raw = (
            args.min_amount
            if getattr(args, "min_amount", None) is not None
            else red.get("min_amount")
        )
        max_raw = (
            args.max_amount
            if getattr(args, "max_amount", None) is not None
            else red.get("max_amount")
        )
        min_amt = float(min_raw) if min_raw is not None else None
        max_amt = float(max_raw) if max_raw is not None else None

    if args.debug_token:
        await debug_storage_keys(cfg, base_url)
        return 0

    token = await resolve_token(cfg, base_url)
    print(f"[INFO] API: {base_url}")
    if do_redirect:
        amt_parts = []
        if min_amt is not None:
            amt_parts.append(f">= {min_amt:g}")
        if max_amt is not None:
            amt_parts.append(f"<= {max_amt:g}")
        labels = ", ".join(f"{lab}({tid[:8]}…)" for lab, tid in traders)
        skip_hint = ", ".join(
            [*(f"BIN {p}*" for p in skip_prefixes), *skip_bank_patterns]
        ) or "—"
        print(
            f"[INFO] Редирект status={deal_status}: "
            f"max={max_per_run or '∞'}, "
            f"сумма={' и '.join(amt_parts) if amt_parts else 'любая'}"
        )
        if skip_bog:
            print(f"[INFO] Пропуск (не редиректим): {skip_hint}")
        else:
            print("[INFO] Фильтр BOG выключен — все подряд")
        if visa_only:
            print("[INFO] Только Visa (карты 4…)")
        print(f"[INFO] Аккаунты (равномерно): {labels}")
    else:
        bits = []
        if patterns:
            bits.append(f"имя∈{patterns}")
        if card_prefixes:
            bits.append(f"BIN {', '.join(p + '*' for p in card_prefixes)}")
        print(f"[INFO] Фильтр отмены ({bank_label}): {'; '.join(bits) or '—'}")
    mode_label = "РЕДИРЕКТ" if do_redirect else "ОТМЕНА"
    print(f"[INFO] Режим: {mode_label}{' (execute)' if args.execute else ' dry-run'}\n")

    rows = fetch_deals_by_status(
        base_url, token, cfg, deal_status=deal_status
    )
    print(f"[INFO] findNew: {len(rows)} сделок со status={deal_status}\n")

    if args.list:
        seen: dict[str, int] = {}
        for row in rows:
            bank = recipient_bank_name(row) or "(нет additionalBankInfo.bank)"
            digits = account_digits(row)
            tag = f"{bank}"
            if digits:
                tag = f"{bank} …{digits[:6]}"
            seen[tag] = seen.get(tag, 0) + 1
        for tag, count in sorted(seen.items(), key=lambda x: (-x[1], x[0].lower())):
            # восстановить грубый row для match/skip
            name = tag.split(" …")[0]
            prefix6 = ""
            if " …" in tag:
                prefix6 = tag.split(" …", 1)[1]
            fake = {
                "credentials": {
                    "additionalBankInfo": {"bank": name},
                    "accountNumber": prefix6,
                }
            }
            mark = ""
            if do_redirect and skip_bog and should_skip_redirect(fake, cfg):
                mark = " ← skip redirect"
            elif (not do_redirect) and deal_matches_bank(
                fake, patterns=patterns, card_prefixes=card_prefixes
            ):
                mark = " ← match"
            print(f"  [{count:2d}] {tag}{mark}")
        return 0

    candidates: list[dict[str, Any]] = []
    skipped_bog = 0
    skipped_non_visa = 0
    for row in rows:
        if do_redirect:
            if skip_bog and should_skip_redirect(row, cfg):
                skipped_bog += 1
                continue
            if visa_only and not is_visa_card(row):
                skipped_non_visa += 1
                continue
            if not _amount_in_range(
                _deal_amount(row), min_amount=min_amt, max_amount=max_amt
            ):
                continue
        else:
            if not deal_matches_bank(
                row, patterns=patterns, card_prefixes=card_prefixes
            ):
                continue
        candidates.append(row)

    if do_redirect and skipped_bog:
        print(
            f"[INFO] Пропущено (BOG/548888 и т.п.): {skipped_bog}"
        )
    if do_redirect and skipped_non_visa:
        print(f"[INFO] Пропущено (не Visa): {skipped_non_visa}")

    if do_redirect and max_per_run > 0:
        candidates = candidates[:max_per_run]

    if not candidates:
        print("[OK] Подходящих сделок не найдено.")
        _emit_ui_result(
            {
                "phase": "done",
                "action": action,
                "cancelled": 0,
                "redirected": 0,
                "failed": 0,
                "total": 0,
                "message": "Подходящих сделок не нашлось",
                "deals": [],
            }
        )
        return 0

    verb = "редиректу" if do_redirect else "отмене"
    print(f"[INFO] К {verb}: {len(candidates)}\n")
    done_ok = 0
    failed = 0
    deals_ui: list[dict[str, Any]] = []
    for i, row in enumerate(candidates):
        deal_id = str(row.get("_id") or "")
        if not deal_id:
            print(f"[WARN] пропуск без _id: {_deal_summary(row)}")
            failed += 1
            deals_ui.append(
                _deal_ui_row(row, ok=False, error="Нет id сделки")
            )
            continue
        print(f"  • {_deal_summary(row)}")
        print(f"    _id={deal_id}")
        trader_label = ""
        trader_id = ""
        if do_redirect:
            trader_label, trader_id = _pick_trader(traders, index=i)
            print(f"    → {trader_label} traderId={trader_id}")
        if not args.execute:
            ui = _deal_ui_row(row, ok=True)
            if trader_label:
                ui["bank"] = trader_label
            deals_ui.append(ui)
            continue
        try:
            if do_redirect:
                status, body = redirect_deal(
                    base_url, token, deal_id, trader_id
                )
                print(f"    → rematch HTTP {status} {body!r}")
            else:
                status, body = cancel_deal(base_url, token, deal_id)
                print(f"    → cancel HTTP {status} {body!r}")
            if 200 <= int(status) < 300:
                done_ok += 1
                ui = _deal_ui_row(row, ok=True)
                if trader_label:
                    ui["bank"] = trader_label
                deals_ui.append(ui)
            else:
                failed += 1
                deals_ui.append(
                    _deal_ui_row(row, ok=False, error=f"Ответ сервера {status}")
                )
        except RuntimeError as exc:
            print(f"    → ОШИБКА: {exc}")
            failed += 1
            deals_ui.append(_deal_ui_row(row, ok=False, error=str(exc)))

    total = len(candidates)
    if args.execute:
        word = "Редирект" if do_redirect else "Отменено"
        print(f"\n[OK] {word}: {done_ok}/{total}")
        if failed:
            msg = f"{word} {done_ok} из {total}, с ошибкой {failed}"
        elif done_ok:
            msg = f"{word} {done_ok} из {total}"
        else:
            msg = (
                "Ни одну сделку редиректнуть не удалось"
                if do_redirect
                else "Ни одну сделку отменить не удалось"
            )
        _emit_ui_result(
            {
                "phase": "done",
                "action": action,
                "cancelled": 0 if do_redirect else done_ok,
                "redirected": done_ok if do_redirect else 0,
                "failed": failed,
                "total": total,
                "message": msg,
                "deals": deals_ui,
            }
        )
    else:
        print(
            "\n[INFO] Dry-run — для выполнения добавьте --execute"
        )
        _emit_ui_result(
            {
                "phase": "done",
                "action": action,
                "cancelled": 0,
                "redirected": 0,
                "failed": 0,
                "total": total,
                "message": (
                    f"Проверка: нашлось {total} сделок "
                    f"(без {'редиректа' if do_redirect else 'отмены'})"
                ),
                "deals": deals_ui,
            }
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Отмена new-сделок по банку / редирект по сумме (API)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="реально вызвать API (cancel или rematch)",
    )
    parser.add_argument(
        "--redirect",
        action="store_true",
        help="редирект: PUT .../rematch-friendly-trader",
    )
    parser.add_argument(
        "--skip-bog",
        action="store_true",
        help="при --redirect: не редиректить Bank of Georgia / 548888…",
    )
    parser.add_argument(
        "--visa-only",
        action="store_true",
        help="при --redirect: только Visa (номер начинается с 4)",
    )
    parser.add_argument(
        "--bank",
        choices=("tbc", "bog"),
        default="tbc",
        help="для отмены: tbc или bog (Bank of Georgia / карты 548888…)",
    )
    parser.add_argument(
        "--deal-status",
        choices=("new", "pending"),
        default="new",
        help="статус для findNew (new по умолчанию; pending — отдельно)",
    )
    parser.add_argument(
        "--trader-id",
        action="append",
        dest="trader_ids",
        default=None,
        help="UUID аккаунта (можно несколько раз; равномерно)",
    )
    parser.add_argument(
        "--trader-label",
        action="append",
        dest="trader_labels",
        default=None,
        help="Метка из config (104.1 / 104.2), можно несколько",
    )
    parser.add_argument("--max-per-run", type=int, default=None)
    parser.add_argument("--min-amount", type=float, default=None)
    parser.add_argument("--max-amount", type=float, default=None)
    parser.add_argument("--list", action="store_true", help="список банков в findNew")
    parser.add_argument("--debug-token", action="store_true", help="ключи localStorage")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
