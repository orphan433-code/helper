"""Подсказки из текста команды — страховка если Gemini промахнулся."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agent.bin_resolve import (
    extract_prefixes_from_text,
    extract_redirect_prefixes_from_text,
)

if TYPE_CHECKING:
    from agent.schema import ActionPlan

_DECLINE_WORDS = ("отмен", "cancel", "сними", "decline", "отклон")
_REDIRECT_WORDS = ("редирект", "передай", "rematch", "redirect", "сделай редирект")
_TBC_WORDS = ("tbc",)
_PENDING_WORDS = ("pending", "пендинг")
_VISA_WORDS = ("visa", "виза")
_SKIP_BOG_WORDS = ("без bog", "skip bog", "не bog")

_COUNT_RE = re.compile(
    r"(\d+)\s*(?:"
    r"сдел(?:к[аиуе]?|ок)?|deal|"
    r"карт(?:[аыуе]?|ок)?|card"
    r")",
    re.IGNORECASE,
)
_ONE_DEAL_RE = re.compile(r"\b1\s+сдел", re.IGNORECASE)
_MAX_AMOUNT_RE = re.compile(
    r"(?:до|max|не\s+более|сумм[аы]?\s*до)\s*(\d+(?:[.,]\d+)?)\s*(?:usdt|usd|\$)?",
    re.IGNORECASE,
)
_MIN_AMOUNT_RE = re.compile(
    r"(?:от|min|не\s+менее|сумм[аы]?\s*от)\s*(\d+(?:[.,]\d+)?)\s*(?:usdt|usd|\$)?",
    re.IGNORECASE,
)
_REMAINING_HOURS_RE = re.compile(
    r"меньше\s+(\d+(?:[.,]\d+)?)\s*(?:ч|час)",
    re.IGNORECASE,
)
_ALL_RE = re.compile(
    r"\b(?:все|всех|всем|всю|all|every)\b",
    re.IGNORECASE,
)


def _float(raw: str) -> float:
    return float(str(raw).replace(",", "."))


def enrich_plan_from_text(plan: ActionPlan, user_text: str) -> ActionPlan:
    """Явные детали в команде → use_ui_defaults=false, UI не подмешивается."""
    from agent.schema import ActionPlan as PlanCls

    text = str(user_text or "")
    low = text.lower()
    out = PlanCls.from_dict(plan.to_dict())
    changed = False

    if any(w in low for w in _REDIRECT_WORDS):
        if out.action != "redirect":
            out.action = "redirect"
            changed = True
    elif any(w in low for w in _DECLINE_WORDS):
        if out.action != "decline":
            out.action = "decline"
            changed = True

    m = _COUNT_RE.search(text)
    if m:
        out.max_per_run = max(1, int(m.group(1)))
        out.all_matching = False
        changed = True
    elif _ONE_DEAL_RE.search(text):
        out.max_per_run = 1
        out.all_matching = False
        changed = True
    elif _ALL_RE.search(low):
        out.max_per_run = 0
        out.all_matching = True
        changed = True

    mm = _MAX_AMOUNT_RE.search(text)
    if mm:
        out.max_amount = _float(mm.group(1))
        changed = True
    mn = _MIN_AMOUNT_RE.search(text)
    if mn:
        out.min_amount = _float(mn.group(1))
        changed = True

    if "меньше часа" in low or ("остаток" in low and "час" in low):
        out.max_remaining = True
        if out.max_remaining_hours <= 0:
            out.max_remaining_hours = 1.0
        changed = True
    rh = _REMAINING_HOURS_RE.search(text)
    if rh:
        out.max_remaining = True
        out.max_remaining_hours = _float(rh.group(1))
        changed = True

    if any(w in low for w in _TBC_WORDS):
        out.decline_tbc = True
        changed = True
    if any(w in low for w in _PENDING_WORDS):
        out.deal_status = "pending"
        changed = True
    if any(w in low for w in _VISA_WORDS):
        out.visa_only = True
        changed = True
    if any(w in low for w in _SKIP_BOG_WORDS):
        out.skip_bog = True
        changed = True

    if out.action == "redirect":
        rb, rp = extract_redirect_prefixes_from_text(text)
        if rb or rp:
            out.redirect_bins = rb
            out.redirect_card_prefixes = rp
            changed = True
    else:
        bins, prefs = extract_prefixes_from_text(text)
        if bins or prefs:
            out.decline_bins = bins
            out.decline_card_prefixes = prefs
            changed = True

    if changed:
        out.use_ui_defaults = False
    out.use_ui_defaults = False
    return out
