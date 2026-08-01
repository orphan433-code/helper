"""In-memory сессия completion — без записи в файл."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platcore_pipeline import AcceptedDeal


class DealCompletionState(str, Enum):
    AWAITING_PROOF = "awaiting_proof"
    PROOF_MATCHED = "proof_matched"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SKIPPED = "skipped"  # Accept был, банк нет — серая, ждёт Отмену


@dataclass
class SessionDeal:
    index: int
    order_id: str
    account_digits: str
    holder_name: str = ""
    amount_tjs: str = ""
    amount_target: str = ""
    amount_usdt: float = 0.0
    needs_video: bool = False
    state: DealCompletionState = DealCompletionState.AWAITING_PROOF
    proof_path: str = ""
    video_path: str = ""
    error: str = ""


@dataclass
class CompletionSession:
    deals: list[SessionDeal] = field(default_factory=list)
    watch_started_at: float = 0.0
    used_proofs: set[str] = field(default_factory=set)
    used_videos: set[str] = field(default_factory=set)
    # Отмена в UI только после первого скана/обработки чеков (или чек+видео)
    cancel_unlocked: bool = False
    video_min_usdt: float = 225.0

    def pending(self) -> list[SessionDeal]:
        return [
            d
            for d in self.deals
            if d.state
            in (DealCompletionState.AWAITING_PROOF, DealCompletionState.PROOF_MATCHED)
        ]

    def unresolved(self) -> list[SessionDeal]:
        """Ещё не закрыты: ждут чек / matched / ошибка / пропуск (cancel)."""
        return [
            d
            for d in self.deals
            if d.state
            in (
                DealCompletionState.AWAITING_PROOF,
                DealCompletionState.PROOF_MATCHED,
                DealCompletionState.FAILED,
                DealCompletionState.SKIPPED,
            )
        ]

    def completed_count(self) -> int:
        return sum(
            1
            for d in self.deals
            if d.state
            in (DealCompletionState.COMPLETED, DealCompletionState.CANCELLED)
        )

    def cancelled_count(self) -> int:
        return sum(
            1 for d in self.deals if d.state == DealCompletionState.CANCELLED
        )


def build_session(
    accepted_deals: list[AcceptedDeal],
    *,
    grace_sec: float = 5.0,
    video_min_usdt: float = 225.0,
) -> CompletionSession:
    deals: list[SessionDeal] = []
    threshold = float(video_min_usdt)
    # Последняя принятая сверху: #1 Accept → внизу списка ожидания чеков
    for accepted in reversed(accepted_deals):
        deal = accepted.deal
        d = accepted.data
        inp = d["amount_input"]
        ver = d["amount_verify"]
        amount_usdt = float(getattr(accepted, "amount_usdt", 0.0) or 0.0)
        bank_skipped = bool(getattr(accepted, "bank_skipped", False))
        deals.append(
            SessionDeal(
                index=accepted.index,
                order_id=accepted.order_id or deal.order_id,
                account_digits=deal.account_digits,
                holder_name=deal.holder_name or "",
                amount_tjs=f"{inp['value']:g} {inp['currency']}",
                amount_target=f"{ver['value']:g} {ver['currency']}",
                amount_usdt=amount_usdt,
                needs_video=False if bank_skipped else amount_usdt > threshold,
                state=(
                    DealCompletionState.SKIPPED
                    if bank_skipped
                    else DealCompletionState.AWAITING_PROOF
                ),
                error="Перевод не выполнен" if bank_skipped else "",
            )
        )
    return CompletionSession(
        deals=deals,
        watch_started_at=time.time() - grace_sec,
        video_min_usdt=threshold,
    )
