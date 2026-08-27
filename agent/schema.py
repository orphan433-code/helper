"""Structured plan для отмены / редиректа."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from core.decline_bins import clamp_decline_limit
from core.redirect_bins import normalize_redirect_prefixes

from agent.bin_resolve import (
    merge_decline_bins_and_prefixes,
    merge_redirect_bins_and_prefixes,
)

ActionKind = Literal["decline", "redirect"]


def _opt_float(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class ActionPlan:
    action: ActionKind
    max_per_run: int = 10
    min_amount: float | None = None
    max_amount: float | None = None
    deal_status: str = "new"
    decline_bins: list[str] = field(default_factory=list)
    decline_card_prefixes: list[str] = field(default_factory=list)
    decline_tbc: bool = False
    redirect_bins: list[str] = field(default_factory=list)
    redirect_card_prefixes: list[str] = field(default_factory=list)
    trader_ids: list[str] = field(default_factory=list)
    trader_labels: list[str] = field(default_factory=list)
    skip_bog: bool = False
    visa_only: bool = False
    mastercard_only: bool = False
    max_remaining: bool = False
    max_remaining_hours: float = 1.0
    all_matching: bool = False
    use_ui_defaults: bool = False
    confidence: float = 0.0
    explanation: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ActionPlan:
        action = str(raw.get("action") or "decline").strip().lower()
        if action not in ("decline", "redirect"):
            action = "decline"
        status = str(raw.get("deal_status") or "new").strip().lower() or "new"
        if status not in ("new", "pending"):
            status = "new"
        try:
            hours = float(raw.get("max_remaining_hours") or 1.0)
        except (TypeError, ValueError):
            hours = 1.0
        if hours <= 0:
            hours = 1.0
        limit_raw = raw.get("max_per_run", 10)
        all_match = bool(raw.get("all_matching"))
        if all_match:
            limit = 0
        elif action == "decline":
            limit = clamp_decline_limit(limit_raw)
        else:
            try:
                n = int(limit_raw)
            except (TypeError, ValueError):
                n = 10
            # 0 = без лимита (∞). Никогда max(1, 0) → 1
            limit = 0 if n <= 0 else n
        bins, card_pref = merge_decline_bins_and_prefixes(
            raw.get("decline_bins"),
            raw.get("decline_card_prefixes"),
        )
        r_bins, r_card = merge_redirect_bins_and_prefixes(
            raw.get("redirect_bins"),
            raw.get("redirect_card_prefixes"),
        )
        if not r_bins and not r_card:
            r_bins = normalize_redirect_prefixes(raw.get("redirect_bins"))
        return cls(
            action=action,  # type: ignore[arg-type]
            max_per_run=limit,
            min_amount=_opt_float(raw.get("min_amount")),
            max_amount=_opt_float(raw.get("max_amount")),
            deal_status=status,
            decline_bins=bins,
            decline_card_prefixes=card_pref,
            decline_tbc=bool(raw.get("decline_tbc")),
            redirect_bins=r_bins,
            redirect_card_prefixes=r_card,
            trader_ids=[
                str(x).strip()
                for x in (raw.get("trader_ids") or [])
                if str(x).strip()
            ],
            trader_labels=[
                str(x).strip()
                for x in (raw.get("trader_labels") or [])
                if str(x).strip()
            ],
            skip_bog=bool(raw.get("skip_bog")),
            visa_only=bool(raw.get("visa_only")),
            mastercard_only=bool(raw.get("mastercard_only")),
            max_remaining=bool(raw.get("max_remaining")),
            max_remaining_hours=hours,
            all_matching=bool(raw.get("all_matching")),
            use_ui_defaults=bool(raw.get("use_ui_defaults", False)),
            confidence=float(raw.get("confidence") or 0.0),
            explanation=str(raw.get("explanation") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def finalize(self) -> ActionPlan:
        """После merge/hints: all_matching → max_per_run=0 (не 1)."""
        out = ActionPlan.from_dict(self.to_dict())
        if out.all_matching:
            out.max_per_run = 0
        return out

    def merge_agent_context(self, ctx: dict[str, Any]) -> ActionPlan:
        """AI-команда: аккаунты редиректа всегда из UI «Куда». Запрос не меняет."""
        out = ActionPlan.from_dict(self.to_dict())
        out.use_ui_defaults = False
        if out.action != "redirect":
            return out
        ids = [
            str(x).strip()
            for x in (ctx.get("redirect_selected_trader_ids") or [])
            if str(x).strip()
        ]
        out.trader_ids = ids
        out.trader_labels = []
        if not ids:
            return out
        traders = ctx.get("available_traders") or []
        by_id: dict[str, str] = {}
        if isinstance(traders, list):
            for item in traders:
                if not isinstance(item, dict):
                    continue
                tid = str(item.get("id") or "").strip()
                label = str(item.get("label") or "").strip()
                if tid and label:
                    by_id[tid] = label
        labels: list[str] = []
        for tid in ids:
            label = by_id.get(tid)
            if label and label not in labels:
                labels.append(label)
        out.trader_labels = labels
        return out

    def merge_ui_context(self, ctx: dict[str, Any]) -> ActionPlan:
        """Legacy alias — для агента только merge_agent_context."""
        return self.merge_agent_context(ctx)

    def human_summary(self) -> str:
        """Короткая строка для логов/диалогов. UI рисует план по полям."""
        lines: list[str] = []
        if self.action == "decline":
            head = (
                "Отмена — все подходящие"
                if self.all_matching
                else f"Отмена — до {self.max_per_run} сделок"
            )
            lines.append(head)
            if self.decline_tbc:
                lines.append("Банк: TBC")
            if self.decline_bins:
                lines.append("BIN: " + ", ".join(self.decline_bins))
            if self.decline_card_prefixes:
                lines.append(
                    "Карты: " + ", ".join(p + "*" for p in self.decline_card_prefixes)
                )
        else:
            head = (
                "Редирект — все подходящие"
                if self.all_matching
                else f"Редирект — до {self.max_per_run} сделок"
            )
            lines.append(head)
            if self.redirect_bins:
                lines.append("BIN: " + ", ".join(self.redirect_bins))
            if self.redirect_card_prefixes:
                lines.append(
                    "Карты: " + ", ".join(p + "*" for p in self.redirect_card_prefixes)
                )
            if self.trader_labels:
                lines.append("Аккаунты: " + ", ".join(self.trader_labels))
            elif self.trader_ids:
                lines.append(f"Аккаунты: {len(self.trader_ids)}")
        if self.deal_status != "new":
            lines.append(f"Статус: {self.deal_status.upper()}")
        amt: list[str] = []
        if self.min_amount is not None:
            amt.append(f"от {self.min_amount:g}")
        if self.max_amount is not None:
            amt.append(f"до {self.max_amount:g}")
        if amt:
            lines.append("Сумма: " + " ".join(amt) + " USDT")
        if self.max_remaining:
            lines.append(f"Остаток: меньше {self.max_remaining_hours:g} ч")
        if self.visa_only:
            lines.append("Только Visa")
        if self.mastercard_only:
            lines.append("Только Mastercard")
        if self.skip_bog:
            lines.append("Без BoG")
        return "\n".join(lines)

    def validate(self) -> str | None:
        if self.visa_only and self.mastercard_only:
            return "Нельзя Visa и Mastercard одновременно"
        if self.action == "decline":
            has_card = bool(
                self.decline_bins
                or self.decline_card_prefixes
                or self.decline_tbc
                or self.visa_only
                or self.mastercard_only
            )
            has_other = (
                self.min_amount is not None
                or self.max_amount is not None
                or self.max_remaining
                or self.all_matching
                or self.max_per_run != 10
            )
            if not has_card and self.use_ui_defaults:
                return "Укажи BIN, префикс карты (5598…), Visa/MC или TBC для отмены"
            if not has_card and not has_other:
                return "Уточни фильтры: BIN/префикс, Visa/MC, сумму, лимит или «все»"
        return None

    def apply_text_hints(self, user_text: str) -> ActionPlan:
        """Цифры/суммы/лимиты из команды важнее UI."""
        from agent.text_hints import enrich_plan_from_text

        return enrich_plan_from_text(self, user_text)
