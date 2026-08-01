"""Реестр сделок, ожидающих чек и Money sent на PlatCore."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from config_loader import ROOT, completion_settings
from platcore_list import extract_deal_id_from_url


class CompletionState(str, Enum):
    AWAITING_PROOF = "awaiting_proof"
    PROOF_MATCHED = "proof_matched"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CompletionDeal:
    index: int
    order_id: str
    account_digits: str
    platcore_url: str
    state: CompletionState = CompletionState.AWAITING_PROOF
    proof_path: str = ""
    holder_name: str = ""
    amount_tjs: float = 0.0
    amount_eur: float = 0.0
    error: str = ""

    @property
    def deal_id(self) -> str:
        from_url = extract_deal_id_from_url(self.platcore_url)
        return from_url or self.order_id

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompletionDeal:
        state_raw = str(raw.get("state") or CompletionState.AWAITING_PROOF.value)
        try:
            state = CompletionState(state_raw)
        except ValueError:
            state = CompletionState.AWAITING_PROOF
        return cls(
            index=int(raw.get("index") or 0),
            order_id=str(raw.get("order_id") or ""),
            account_digits=str(raw.get("account_digits") or ""),
            platcore_url=str(raw.get("platcore_url") or ""),
            state=state,
            proof_path=str(raw.get("proof_path") or ""),
            holder_name=str(raw.get("holder_name") or ""),
            amount_tjs=float(raw.get("amount_tjs") or 0.0),
            amount_eur=float(raw.get("amount_eur") or 0.0),
            error=str(raw.get("error") or ""),
        )


@dataclass
class CompletionBatch:
    created_at: float = field(default_factory=time.time)
    deals: list[CompletionDeal] = field(default_factory=list)
    last_scan_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "last_scan_at": self.last_scan_at,
            "deals": [deal.to_dict() for deal in self.deals],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompletionBatch:
        deals = [CompletionDeal.from_dict(item) for item in raw.get("deals") or []]
        return cls(
            created_at=float(raw.get("created_at") or time.time()),
            deals=deals,
            last_scan_at=float(raw.get("last_scan_at") or 0.0),
        )


def batch_path(cfg: dict | None = None) -> Path:
    rel = completion_settings(cfg).get("batch_file") or "completion_batch.json"
    path = Path(rel)
    if not path.is_absolute():
        path = ROOT / path
    return path


def proofs_dir(cfg: dict | None = None) -> Path:
    rel = completion_settings(cfg).get("proofs_dir") or "~/Downloads"
    path = Path(rel).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def videos_dir(cfg: dict | None = None) -> Path:
    """Папка для режима «Видео + чеки» (скрины и ролики) — Downloads на Mac."""
    rel = completion_settings(cfg).get("videos_dir") or "~/Downloads"
    path = Path(rel).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_platcore_deal_url(monitor_url: str, deal_id: str) -> str:
    base = monitor_url.split("?")[0]
    return f"{base}?dealId={deal_id}"


def load_batch(cfg: dict | None = None) -> CompletionBatch:
    path = batch_path(cfg)
    if not path.exists():
        return CompletionBatch()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CompletionBatch()
    if isinstance(raw, list):
        return CompletionBatch(deals=[CompletionDeal.from_dict(item) for item in raw])
    return CompletionBatch.from_dict(raw)


def save_batch(batch: CompletionBatch, cfg: dict | None = None) -> Path:
    path = batch_path(cfg)
    path.write_text(
        json.dumps(batch.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def pending_deals(batch: CompletionBatch) -> list[CompletionDeal]:
    return [
        deal
        for deal in batch.deals
        if deal.state in (CompletionState.AWAITING_PROOF, CompletionState.PROOF_MATCHED)
    ]


def register_single_deal(
    accepted: Any,
    *,
    monitor_url: str,
    cfg: dict | None = None,
) -> CompletionDeal | None:
    comp = completion_settings(cfg)
    if not comp.get("enabled", True):
        return None

    batch = load_batch(cfg)
    deal = accepted.deal
    order_id = accepted.order_id or deal.order_id
    if not order_id:
        return None

    for existing in batch.deals:
        if existing.order_id == order_id:
            return existing

    platcore_url = ""
    page = getattr(accepted, "platcore_page", None)
    if page is not None and not page.is_closed():
        platcore_url = page.url
    if not platcore_url:
        platcore_url = build_platcore_deal_url(monitor_url, order_id)

    record = CompletionDeal(
        index=accepted.index,
        order_id=order_id,
        account_digits=deal.account_digits,
        platcore_url=platcore_url,
        holder_name=deal.holder_name or "",
        amount_tjs=float(deal.amount_tjs or 0.0),
        amount_eur=float(deal.amount_eur or 0.0),
    )
    batch.deals.append(record)
    save_batch(batch, cfg)
    return record


def register_accepted_deals(
    accepted_deals: list[Any],
    *,
    monitor_url: str,
    cfg: dict | None = None,
) -> CompletionBatch:
    """Добавить принятые сделки в реестр (без дублей по order_id)."""
    batch = load_batch(cfg)
    known = {deal.order_id for deal in batch.deals if deal.order_id}
    for accepted in accepted_deals:
        deal = accepted.deal
        order_id = accepted.order_id or deal.order_id
        if not order_id or order_id in known:
            continue
        platcore_url = ""
        page = getattr(accepted, "platcore_page", None)
        if page is not None and not page.is_closed():
            platcore_url = page.url
        if not platcore_url and order_id:
            platcore_url = build_platcore_deal_url(monitor_url, order_id)
        batch.deals.append(
            CompletionDeal(
                index=accepted.index,
                order_id=order_id,
                account_digits=deal.account_digits,
                platcore_url=platcore_url,
                holder_name=deal.holder_name or "",
                amount_tjs=float(deal.amount_tjs or 0.0),
                amount_eur=float(deal.amount_eur or 0.0),
            )
        )
        known.add(order_id)
    save_batch(batch, cfg)
    return batch


def attach_proof(
    order_id: str,
    proof_path: Path | str,
    *,
    cfg: dict | None = None,
) -> CompletionDeal | None:
    batch = load_batch(cfg)
    path_text = str(proof_path)
    for deal in batch.deals:
        if deal.order_id != order_id:
            continue
        if deal.state == CompletionState.COMPLETED:
            return deal
        deal.proof_path = path_text
        deal.state = CompletionState.PROOF_MATCHED
        save_batch(batch, cfg)
        return deal
    return None


def mark_completed(order_id: str, *, cfg: dict | None = None) -> None:
    batch = load_batch(cfg)
    for deal in batch.deals:
        if deal.order_id == order_id:
            deal.state = CompletionState.COMPLETED
            deal.error = ""
            break
    save_batch(batch, cfg)


def mark_failed(order_id: str, error: str, *, cfg: dict | None = None) -> None:
    batch = load_batch(cfg)
    for deal in batch.deals:
        if deal.order_id == order_id:
            deal.state = CompletionState.FAILED
            deal.error = error
            break
    save_batch(batch, cfg)


def used_proof_paths(batch: CompletionBatch) -> set[str]:
    return {
        deal.proof_path
        for deal in batch.deals
        if deal.proof_path
    }
