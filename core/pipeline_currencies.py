"""Фильтр фиат-валюты перед Accept. Пусто = любые."""

from __future__ import annotations

PIPELINE_CURRENCIES: tuple[str, ...] = ("EUR", "THB", "TRY")


def normalize_pipeline_currencies(raw: object) -> list[str]:
    if raw is None or raw is False:
        return []
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.replace(",", " ").split() if p.strip()]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(x).strip().upper() for x in raw if str(x).strip()]
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for code in parts:
        if len(code) != 3 or not code.isalpha() or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def gui_pipeline_currencies(raw: object) -> list[str]:
    """Только EUR/THB/TRY — то, что рисуем в фильтрах."""
    selected = set(normalize_pipeline_currencies(raw))
    return [c for c in PIPELINE_CURRENCIES if c in selected]


def pipeline_currencies_from_cfg(cfg: dict | None) -> list[str]:
    flow = (cfg or {}).get("api_flow") or {}
    if not isinstance(flow, dict):
        return []
    return normalize_pipeline_currencies(flow.get("currencies"))


def skip_reason_for_currency(code: str, currencies: list[str] | None) -> str | None:
    if not currencies:
        return None
    cur = (code or "").strip().upper()
    allowed = {c.upper() for c in currencies}
    if cur not in allowed:
        return f"валюта {cur or '—'} не в фильтре ({', '.join(currencies)})"
    return None


def fiat_code_from_amount_raw(amount_raw: str) -> str:
    from core.validators import PanicError, parse_amount

    try:
        _, code = parse_amount(amount_raw or "")
    except PanicError:
        return ""
    return (code or "").strip().upper()
