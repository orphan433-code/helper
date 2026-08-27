"""Preview matching deals для ActionPlan."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from core.paths import ROOT

from agent.platcore_session import acquire_token, load_decline_config
from agent.schema import ActionPlan
from agent.trace import agent_trace

_DECLINE_DIR = ROOT / "platcore-decline"
if str(_DECLINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DECLINE_DIR))

import decline_by_bank_api as dapi  # noqa: E402


def _deal_row(row: dict[str, Any], *, trader_label: str = "") -> dict[str, Any]:
    creds = row.get("credentials") or {}
    card = str(creds.get("accountNumber") or "")
    last4 = card[-4:] if len(card) >= 4 else "????"
    amount = row.get("amount")
    left = dapi.deal_remaining_seconds(row)
    h, rem = divmod(int(left) if left and left > 0 else 0, 3600)
    m, s = divmod(rem, 60)
    remaining = f"{h:02d}:{m:02d}:{s:02d}" if left is not None else "?"
    return {
        "order_id": str(row.get("orderId") or ""),
        "card": f"*{last4}" if last4 != "????" else "????",
        "holder": str(creds.get("ownerName") or "").strip(),
        "amount": "" if amount is None else str(amount),
        "bank": trader_label or (dapi.recipient_bank_name(row) or ""),
        "remaining": remaining,
        "ok": True,
    }


def _decline_rules(plan: ActionPlan, cfg: dict) -> tuple[list[str], list[str], bool]:
    patterns: list[str] = []
    card_prefixes: list[str] = list(plan.decline_bins) + list(plan.decline_card_prefixes)
    include_tbc = bool(plan.decline_tbc)
    if include_tbc:
        tbc_pats, tbc_prefs, _ = dapi._decline_match_rules(cfg, bank_preset="tbc")
        patterns = list(tbc_pats)
        for p in tbc_prefs:
            if p not in card_prefixes:
                card_prefixes.append(p)
    return patterns, card_prefixes, include_tbc


def _resolve_traders(plan: ActionPlan, cfg: dict) -> list[tuple[str, str]]:
    if not plan.trader_ids and not plan.trader_labels:
        return []
    return dapi._resolve_active_traders(
        cfg,
        cli_ids=plan.trader_ids or None,
        cli_labels=plan.trader_labels or None,
    )


async def preview_plan(plan: ActionPlan) -> dict[str, Any]:
    cfg = load_decline_config()
    agent_trace(f"preview: action={plan.action} max={plan.max_per_run}")
    token, base_url, token_source = await acquire_token(cfg)
    agent_trace(f"preview: token from {token_source}, api={base_url}")
    status = str(plan.deal_status or "new").strip().lower() or "new"

    steps: list[dict[str, str]] = [
        {"step": "token", "detail": f"Токен ({token_source})"},
        {
            "step": "findNew",
            "detail": f"GET /api/deals/findNew status={status}",
        },
    ]

    rows = dapi.fetch_deals_by_status(base_url, token, cfg, deal_status=status)
    total_pool = len(rows)
    agent_trace(f"preview: findNew status={status} → {total_pool} rows")
    steps.append({"step": "pool", "detail": f"В пуле: {total_pool}"})

    candidates: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    if plan.action == "redirect":
        traders = _resolve_traders(plan, cfg)
        redirect_prefixes = list(plan.redirect_bins) + list(plan.redirect_card_prefixes)
        for row in rows:
            if plan.skip_bog and dapi.should_skip_redirect(row, cfg):
                skipped["bog"] = skipped.get("bog", 0) + 1
                continue
            if redirect_prefixes and not dapi.card_prefix_matches(
                dapi.account_digits(row), redirect_prefixes
            ):
                skipped["bin"] = skipped.get("bin", 0) + 1
                continue
            if plan.visa_only and not dapi.is_visa_card(row):
                skipped["visa"] = skipped.get("visa", 0) + 1
                continue
            if plan.mastercard_only and not dapi.is_mastercard_card(row):
                skipped["mastercard"] = skipped.get("mastercard", 0) + 1
                continue
            if plan.max_remaining and not dapi.remaining_under_hours(
                row, plan.max_remaining_hours
            ):
                skipped["remaining"] = skipped.get("remaining", 0) + 1
                continue
            if not dapi._amount_in_range(
                dapi._deal_amount(row),
                min_amount=plan.min_amount,
                max_amount=plan.max_amount,
            ):
                skipped["amount"] = skipped.get("amount", 0) + 1
                continue
            candidates.append(row)
        limit = plan.max_per_run
        if limit > 0:
            candidates = candidates[:limit]
        deals_ui: list[dict[str, Any]] = []
        for i, row in enumerate(candidates):
            label = ""
            if traders:
                label, _tid = dapi._pick_trader(traders, index=i)
            deals_ui.append(_deal_row(row, trader_label=label))
    else:
        patterns, card_prefixes, _tbc = _decline_rules(plan, cfg)
        ui_filter = bool(card_prefixes) or _tbc
        for row in rows:
            if ui_filter and not dapi.deal_matches_bank(
                row, patterns=patterns, card_prefixes=card_prefixes
            ):
                skipped["bank"] = skipped.get("bank", 0) + 1
                continue
            if plan.visa_only and not dapi.is_visa_card(row):
                skipped["visa"] = skipped.get("visa", 0) + 1
                continue
            if plan.mastercard_only and not dapi.is_mastercard_card(row):
                skipped["mastercard"] = skipped.get("mastercard", 0) + 1
                continue
            if plan.max_remaining and not dapi.remaining_under_hours(
                row, plan.max_remaining_hours
            ):
                skipped["remaining"] = skipped.get("remaining", 0) + 1
                continue
            if not dapi._amount_in_range(
                dapi._deal_amount(row),
                min_amount=plan.min_amount,
                max_amount=plan.max_amount,
            ):
                skipped["amount"] = skipped.get("amount", 0) + 1
                continue
            candidates.append(row)
        candidates.sort(key=dapi._remaining_sort_key)
        limit = plan.max_per_run
        if limit > 0:
            candidates = candidates[:limit]
        deals_ui = [_deal_row(row) for row in candidates]

    steps.append(
        {
            "step": "filter",
            "detail": (
                f"После фильтров: {len(deals_ui)} (все подходящие)"
                if plan.all_matching or not plan.max_per_run
                else f"После фильтров: {len(deals_ui)} (лимит {limit})"
            ),
        }
    )

    skip_labels = {
        "amount": "сумма",
        "bank": "банк",
        "bin": "BIN",
        "bog": "BoG",
        "visa": "не Visa",
        "mastercard": "не Mastercard",
        "remaining": "остаток времени",
    }
    skip_parts = [
        f"{skip_labels.get(k, k)} — {v}"
        for k, v in sorted(skipped.items())
        if v
    ]
    summary_lines = [
        f"Пул: {total_pool} ({status.upper()})",
        f"Подходит: {len(deals_ui)}",
    ]
    if skip_parts:
        summary_lines.append("Не прошли фильтр: " + "; ".join(skip_parts))
    summary = "\n".join(summary_lines)
    return {
        "total_pool": total_pool,
        "matched": len(deals_ui),
        "deals": deals_ui,
        "summary": summary,
        "skipped": skipped,
        "plan": plan.to_dict(),
        "steps": steps,
        "token_source": token_source,
    }


def preview_plan_sync(plan: ActionPlan) -> dict[str, Any]:
    return asyncio.run(preview_plan(plan))
