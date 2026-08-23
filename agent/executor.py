"""Запуск decline/redirect по ActionPlan."""

from __future__ import annotations

import sys
from typing import Any

from core.config import load_config
from core.paths import ROOT
from core.redirect_rules import REDIRECT_MAX_REMAINING_HOURS

from agent.schema import ActionPlan

_DECLINE_DIR = ROOT / "platcore-decline"
if str(_DECLINE_DIR) not in sys.path:
    sys.path.insert(0, str(_DECLINE_DIR))

import decline_by_bank_api as dapi  # noqa: E402


def _resolve_trader_ids(plan: ActionPlan) -> list[str]:
    cfg = load_config()
    traders = dapi._resolve_active_traders(
        cfg,
        cli_ids=plan.trader_ids or None,
        cli_labels=plan.trader_labels or None,
    )
    return [tid for _label, tid in traders]


def execute_plan(api: Any, plan: ActionPlan) -> dict[str, Any]:
    """Вызов start_decline / start_redirect. Не трогаем runtime/deals_ui.yaml."""
    if plan.action == "decline":
        return api.start_decline(
            prefixes=list(plan.decline_bins),
            tbc=bool(plan.decline_tbc),
            max_per_run=plan.max_per_run,
            min_amount=plan.min_amount,
            max_amount=plan.max_amount,
            max_remaining=bool(plan.max_remaining),
            max_remaining_hours=plan.max_remaining_hours,
            card_prefixes=list(plan.decline_card_prefixes),
            all_cards=(
                not plan.decline_bins
                and not plan.decline_card_prefixes
                and not plan.decline_tbc
            ),
        )

    trader_ids = _resolve_trader_ids(plan)
    if not trader_ids:
        return api._err("Нет аккаунтов для редиректа")
    hours = plan.max_remaining_hours if plan.max_remaining else REDIRECT_MAX_REMAINING_HOURS
    return api.start_redirect(
        trader_ids=trader_ids,
        max_per_run=plan.max_per_run,
        min_amount=plan.min_amount,
        max_amount=plan.max_amount,
        deal_status=plan.deal_status,
        skip_bog=bool(plan.skip_bog),
        visa_only=bool(plan.visa_only),
        max_remaining=bool(plan.max_remaining),
        max_remaining_hours=hours if plan.max_remaining else None,
        redirect_prefixes=list(plan.redirect_bins),
        redirect_card_prefixes=list(plan.redirect_card_prefixes),
    )
