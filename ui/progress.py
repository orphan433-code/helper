"""Прогресс Accept/Bank и фазы чеков для GUI (pywebview)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from completion.session import CompletionSession, SessionDeal
    from core.models import RowPreview
    from platcore.pipeline import AcceptedDeal

CompletionProgressHandler = Callable[[dict[str, Any]], None]
PipelineProgressHandler = Callable[[dict[str, Any]], None]

_lock = threading.Lock()
_handler: CompletionProgressHandler | None = None
_pipeline_handler: PipelineProgressHandler | None = None


def set_completion_progress_handler(
    handler: CompletionProgressHandler | None,
) -> None:
    global _handler
    with _lock:
        _handler = handler


def clear_completion_progress_handler() -> None:
    set_completion_progress_handler(None)


def set_pipeline_progress_handler(
    handler: PipelineProgressHandler | None,
) -> None:
    global _pipeline_handler
    with _lock:
        _pipeline_handler = handler


def clear_pipeline_progress_handler() -> None:
    set_pipeline_progress_handler(None)


def _card_tag(digits: str) -> str:
    return f"*{digits[-4:]}" if len(digits) >= 4 else "????"


def _deal_to_ui(deal: SessionDeal) -> dict[str, Any]:
    ui_state = {
        "awaiting_proof": "pending",
        "proof_matched": "matched",
        "completed": "done",
        "cancelled": "cancelled",
        "failed": "error",
        "skipped": "skipped",
    }.get(deal.state.value, "pending")
    return {
        "index": deal.index,
        "order_id": deal.order_id or "",
        "card": _card_tag(deal.account_digits),
        "holder": deal.holder_name or "",
        "amount_tjs": deal.amount_tjs,
        "amount_target": deal.amount_target,
        "amount_usdt": float(getattr(deal, "amount_usdt", 0.0) or 0.0),
        "state": ui_state,
        "needs_video": bool(getattr(deal, "needs_video", False)),
        "has_video": bool(deal.video_path),
        "error": deal.error or "",
        "can_cancel": False,
        "can_retry": False,
    }


def _error_detail(session: CompletionSession) -> str:
    lines: list[str] = []
    for d in session.deals:
        if d.state.value != "failed" or not d.error:
            continue
        lines.append(f"#{d.index} {_card_tag(d.account_digits)}: {d.error}")
    return "\n".join(lines)


def notify_completion_progress(
    session: CompletionSession,
    *,
    phase: str,
    message: str = "",
    active_index: int | None = None,
    allow_cancel: bool = False,
) -> None:
    with _lock:
        handler = _handler
    if handler is None:
        return

    done = sum(
        1
        for d in session.deals
        if d.state.value in ("completed", "cancelled")
    )
    failed = sum(1 for d in session.deals if d.state.value == "failed")
    total = len(session.deals)
    cancel_ok = bool(allow_cancel and session.cancel_unlocked)
    deals_ui = []
    for d in session.deals:
        row = _deal_to_ui(d)
        has_id = bool(d.order_id)
        # Пропуск банка — серая; Отмена сразу в фазе чеков (без ожидания скана)
        if d.state.value == "skipped":
            row["can_cancel"] = bool(allow_cancel and has_id)
        else:
            # Остальные — Отмена только без чека и после первого скана
            no_proof = (
                (d.state.value == "awaiting_proof" and not d.proof_path)
                or (d.state.value == "failed" and not d.proof_path)
            )
            row["can_cancel"] = bool(cancel_ok and has_id and no_proof)
        # Повтор — у FAILED с уже найденным чеком (тот же файл)
        row["can_retry"] = bool(
            allow_cancel
            and has_id
            and d.state.value == "failed"
            and bool(d.proof_path)
        )
        # Новый файл — сбросить привязку и снова сканировать
        row["can_rescan"] = bool(
            allow_cancel
            and has_id
            and d.state.value in ("failed", "proof_matched")
        )
        deals_ui.append(row)
    payload: dict[str, Any] = {
        "phase": phase,
        "message": message,
        "done": done,
        "failed": failed,
        "total": total,
        "active_index": active_index,
        "allow_cancel": allow_cancel,
        "error_detail": _error_detail(session),
        "deals": deals_ui,
    }
    try:
        handler(payload)
    except Exception:
        pass


def _digits_tag(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return _card_tag(digits)


def _emit_pipeline(payload: dict[str, Any]) -> None:
    with _lock:
        handler = _pipeline_handler
    if handler is None:
        return
    try:
        handler(payload)
    except Exception:
        pass


@dataclass
class PipelineProgressTracker:
    """Живой прогресс Accept → банк для панели под «Запустить обработку»."""

    total: int
    deals: list[dict[str, Any]] = field(default_factory=list)

    def _counts(self) -> tuple[int, int, int]:
        paid = sum(1 for d in self.deals if d.get("state") == "paid")
        skipped = sum(1 for d in self.deals if d.get("state") == "skipped")
        active = sum(
            1
            for d in self.deals
            if d.get("state") in ("accepting", "accepted", "paying")
        )
        return paid, skipped, active

    def _payload(
        self,
        *,
        phase: str,
        message: str = "",
        active_index: int | None = None,
    ) -> dict[str, Any]:
        paid, skipped, active = self._counts()
        remaining = max(0, self.total - paid - skipped - active)
        return {
            "phase": phase,
            "message": message,
            "paid": paid,
            "skipped": skipped,
            "remaining": remaining,
            "total": self.total,
            "active_index": active_index,
            "deals": [dict(d) for d in self.deals],
        }

    def notify(
        self,
        *,
        phase: str,
        message: str = "",
        active_index: int | None = None,
    ) -> None:
        _emit_pipeline(
            self._payload(
                phase=phase, message=message, active_index=active_index
            )
        )

    def begin_search(self) -> None:
        self.notify(
            phase="searching",
            message=f"Ищу подходящие сделки, нужно {self.total}…",
        )

    def _upsert(self, index: int, **fields: Any) -> dict[str, Any]:
        for row in self.deals:
            if row.get("index") == index:
                row.update(fields)
                return row
        row: dict[str, Any] = {
            "index": index,
            "order_id": "",
            "card": "",
            "holder": "",
            "amount_tjs": "",
            "amount_usdt": 0.0,
            "state": "pending",
            "error": "",
        }
        row.update(fields)
        self.deals.append(row)
        self.deals.sort(key=lambda d: int(d.get("index") or 0))
        return row

    def start_accept(self, index: int, preview: RowPreview) -> None:
        amount_usdt = 0.0
        raw_usdt = getattr(preview, "amount_usdt_raw", "") or ""
        if raw_usdt:
            try:
                from core.validators import parse_amount_value

                amount_usdt = float(parse_amount_value(raw_usdt))
            except Exception:
                amount_usdt = 0.0
        self._upsert(
            index,
            state="accepting",
            card=_digits_tag(getattr(preview, "account_raw", "") or ""),
            holder=(getattr(preview, "holder_raw", "") or "").strip(),
            amount_tjs=(getattr(preview, "amount_raw", "") or "").strip(),
            amount_usdt=amount_usdt,
            error="",
        )
        paid, skipped, _ = self._counts()
        left = max(0, self.total - paid - skipped)
        self.notify(
            phase="processing",
            message=f"Принимаю сделку {index}. Осталось {left}.",
            active_index=index,
        )

    def mark_accepted(self, accepted: AcceptedDeal) -> None:
        data = accepted.data or {}
        account = data.get("account") or {}
        digits = str(account.get("digits") or accepted.deal.account_digits or "")
        inp = data.get("amount_input") or {}
        amount_tjs = ""
        if inp.get("value") is not None and inp.get("currency"):
            amount_tjs = f"{inp['value']:g} {inp['currency']}"
        elif accepted.deal.amount_tjs:
            amount_tjs = f"{accepted.deal.amount_tjs:g} TJS"
        self._upsert(
            accepted.index,
            state="accepted",
            order_id=accepted.order_id or "",
            card=_card_tag(digits),
            holder=(
                (data.get("holder_name") or accepted.deal.holder_name or "")
            ).strip(),
            amount_tjs=amount_tjs,
            amount_usdt=float(getattr(accepted, "amount_usdt", 0.0) or 0.0),
            error="",
        )
        self.notify(
            phase="processing",
            message=f"Сделка {accepted.index} принята. Реквизиты получены.",
            active_index=accepted.index,
        )

    def mark_paying(self, index: int) -> None:
        self._upsert(index, state="paying", error="")
        self.notify(
            phase="processing",
            message=f"Отправляю перевод по сделке {index}…",
            active_index=index,
        )

    def mark_paid(self, index: int) -> None:
        self._upsert(index, state="paid", error="")
        paid, skipped, _ = self._counts()
        left = max(0, self.total - paid - skipped)
        if left:
            msg = f"Сделка {index} выплачена. Готово {paid} из {self.total}, ещё {left}."
        else:
            msg = f"Сделка {index} выплачена. Готово {paid} из {self.total}."
        self.notify(phase="processing", message=msg, active_index=None)

    def mark_skipped(self, index: int, reason: str = "") -> None:
        self._upsert(index, state="skipped", error=(reason or "").strip())
        paid, skipped, _ = self._counts()
        left = max(0, self.total - paid - skipped)
        if left:
            msg = (
                f"Сделка {index} пропущена. "
                f"Выплачено {paid} из {self.total}, ещё {left}."
            )
        else:
            msg = f"Сделка {index} пропущена. Выплачено {paid} из {self.total}."
        self.notify(phase="processing", message=msg, active_index=None)

    def finish(self) -> None:
        paid, skipped, _ = self._counts()
        if skipped:
            msg = (
                f"Обработка закончена. "
                f"Выплачено {paid} из {self.total}, пропущено {skipped}."
            )
        else:
            msg = f"Обработка закончена. Выплачено {paid} из {self.total}."
        self.notify(phase="done", message=msg, active_index=None)
