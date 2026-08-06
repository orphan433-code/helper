"""Фаза 2: та же сессия браузера, вкладки PlatCore открыты → скрины → Money sent."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page

from bank.receipt import ReceiptParseResult, cards_match, parse_receipt_image
from completion.registry import proofs_dir, videos_dir
from completion.session import (
    CompletionSession,
    DealCompletionState,
    SessionDeal,
    build_session,
)
from core.config import completion_settings
from core.human import HumanTiming, parse_human_timing
from ui.progress import notify_completion_progress
from ui.job_control import JobStopped, raise_if_stopped
from core.logkit import debug, error, info, ok, section, warn
from platcore.completion import complete_deal_on_platcore, ensure_dropzone_on_page
from platcore.dispute import parse_dispute_config, submit_dispute_without_proof
from platcore.pipeline import AcceptedDeal
from completion.proof import list_new_proof_files, pick_latest_video
from ui.prompts import wait_user_confirm


@dataclass(frozen=True)
class ProofMatch:
    deal: SessionDeal
    receipt: ReceiptParseResult


_active_lock = threading.Lock()
_active_session: CompletionSession | None = None
_active_cfg: dict | None = None


def set_active_completion_session(
    session: CompletionSession | None,
    cfg: dict | None = None,
) -> None:
    global _active_session, _active_cfg
    with _active_lock:
        _active_session = session
        _active_cfg = cfg


def get_active_completion_session() -> tuple[
    CompletionSession | None, dict | None
]:
    with _active_lock:
        return _active_session, _active_cfg


async def wait_console_enter(prompt: str) -> str:
    return await wait_user_confirm(prompt)


def _card_tag(digits: str) -> str:
    return f"*{digits[-4:]}" if len(digits) >= 4 else "????"


def print_session_status(session: CompletionSession) -> None:
    remaining = session.unresolved()
    done = session.completed_count()
    total = len(session.deals)
    if not remaining:
        ok(f"Чеки: {done}/{total} закрыто")
        return
    cards = ", ".join(_card_tag(d.account_digits) for d in remaining if d.account_digits)
    info(f"Чеки: {done}/{total} готово | ждут: {cards or '—'}")
    for deal in session.deals:
        if deal.state not in (
            DealCompletionState.COMPLETED,
            DealCompletionState.CANCELLED,
            DealCompletionState.AWAITING_PROOF,
        ):
            debug(
                f"#{deal.index} {_card_tag(deal.account_digits)} "
                f"{deal.state.value}"
                + (f" — {deal.error}" if deal.error else "")
            )


def scan_proof_files(
    session: CompletionSession,
    *,
    cfg: dict | None = None,
    folder: Path | None = None,
) -> list[ReceiptParseResult]:
    paths = list_new_proof_files(
        since_ts=session.watch_started_at,
        used_paths=session.used_proofs,
        cfg=cfg,
        folder=folder,
    )
    if not paths:
        debug("Новых файлов в папке чеков нет")
        return []

    results: list[ReceiptParseResult] = []
    for path in paths:
        try:
            parsed = parse_receipt_image(path)
        except Exception as exc:
            warn(f"OCR {path.name}: {exc}")
            continue
        if not parsed.recipient_card:
            debug(f"Пропуск {path.name}: карта не распознана")
            continue
        debug(f"Скан {path.name} → карта {parsed.recipient_card}")
        results.append(parsed)
    return results


def match_proofs_to_deals(
    session: CompletionSession,
    receipts: list[ReceiptParseResult],
    *,
    candidates: list[SessionDeal] | None = None,
    consume: bool = True,
) -> list[ProofMatch]:
    """Сопоставить чеки со сделками.

    consume=True — как раньше, помечает used_proofs.
    consume=False — dry-run для превью (сессию не меняет).
    """
    matches: list[ProofMatch] = []
    assigned: set[str] = set()
    tentatively_used: set[str] = set()

    awaiting = (
        candidates
        if candidates is not None
        else [
            d
            for d in session.deals
            if d.state == DealCompletionState.AWAITING_PROOF
        ]
    )

    for receipt in receipts:
        proof_key = str(receipt.path.resolve())
        if proof_key in session.used_proofs or proof_key in tentatively_used:
            continue
        for deal in awaiting:
            if deal.order_id in assigned:
                continue
            if not cards_match(deal.account_digits, receipt.recipient_card):
                continue
            matches.append(ProofMatch(deal=deal, receipt=receipt))
            assigned.add(deal.order_id)
            tentatively_used.add(proof_key)
            if consume:
                session.used_proofs.add(proof_key)
            break

    return matches


def preview_receipt_readiness(
    session: CompletionSession | None = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Превью без загрузки: какие сделки уже имеют файл в папке."""
    active, active_cfg = get_active_completion_session()
    session = session or active
    cfg = cfg if cfg is not None else active_cfg
    if session is None:
        return {"ok": False, "error": "Фаза чеков не активна", "deals": []}

    screens_dir = proofs_dir(cfg)
    downloads_dir = videos_dir(cfg)

    awaiting = [
        d for d in session.deals if d.state == DealCompletionState.AWAITING_PROOF
    ]

    # Только пропуски / уже закрыто — OCR не гоняем (UI не мигает «чек есть»)
    if not awaiting:
        deals_ui: list[dict[str, Any]] = []
        for deal in session.deals:
            state = deal.state.value
            row: dict[str, Any] = {
                "index": deal.index,
                "order_id": deal.order_id or "",
                "card": _card_tag(deal.account_digits),
                "needs_video": bool(deal.needs_video),
                "state": state,
                "has_shot": False,
                "has_video": False,
                "ready": state in ("completed", "cancelled"),
                "file_name": "",
                "hint": "",
                "can_rescan": False,
            }
            if state == "completed":
                row["hint"] = "загружено"
                row["has_shot"] = bool(deal.proof_path)
                row["file_name"] = (
                    Path(deal.proof_path).name if deal.proof_path else ""
                )
            elif state == "cancelled":
                row["hint"] = "отменена"
            elif state == "skipped":
                row["hint"] = "пропуск банка — Отмена"
            elif state == "failed":
                row["hint"] = deal.error or "ошибка"
                row["has_shot"] = bool(deal.proof_path)
                row["has_video"] = bool(deal.video_path)
                row["can_rescan"] = True
                row["file_name"] = (
                    Path(deal.proof_path).name if deal.proof_path else ""
                )
            deals_ui.append(row)
        return {
            "ok": True,
            "folder": str(downloads_dir),
            "files_found": 0,
            "video_ready": False,
            "video_name": "",
            "ready_count": 0,
            "awaiting_count": 0,
            "total": len(session.deals),
            "all_ready": False,
            "deals": deals_ui,
            "unmatched_files": [],
        }

    large_awaiting = [d for d in awaiting if d.needs_video]
    video_path = None
    if large_awaiting:
        video_path = pick_latest_video(
            since_ts=session.watch_started_at,
            used_paths=session.used_videos,
            cfg=cfg,
            folder=downloads_dir,
        )

    # Превью: матчим чеки и для крупных сделок без видео —
    # чтобы UI показал «чек есть / видео нет». На реальной загрузке
    # крупные без видео по-прежнему не consume'ятся.
    candidates = list(awaiting)
    receipts = _scan_receipts_all_folders(
        session,
        cfg=cfg,
        screens_dir=screens_dir,
        downloads_dir=downloads_dir,
    )
    matches = match_proofs_to_deals(
        session, receipts, candidates=candidates, consume=False
    )
    by_order = {m.deal.order_id: m for m in matches}
    matched_paths = {str(m.receipt.path.resolve()) for m in matches}

    deals_ui = []
    ready_count = 0
    for deal in session.deals:
        state = deal.state.value
        row: dict[str, Any] = {
            "index": deal.index,
            "order_id": deal.order_id or "",
            "card": _card_tag(deal.account_digits),
            "needs_video": bool(deal.needs_video),
            "state": state,
            "has_shot": bool(deal.proof_path),
            "has_video": bool(deal.video_path),
            "ready": state in ("completed", "cancelled"),
            "file_name": Path(deal.proof_path).name if deal.proof_path else "",
            "hint": "",
            "can_rescan": False,
        }
        if state == "completed":
            row["hint"] = "загружено"
            ready_count += 1
        elif state == "cancelled":
            row["hint"] = "отменена"
            ready_count += 1
        elif state == "skipped":
            row["hint"] = "пропуск банка — Отмена"
            row["has_shot"] = False
            row["has_video"] = False
            row["ready"] = False
            row["file_name"] = ""
        elif state == "failed":
            row["hint"] = deal.error or "ошибка — Повторить / Новый файл"
            row["can_rescan"] = True
            row["has_shot"] = bool(deal.proof_path)
            row["has_video"] = bool(deal.video_path)
        elif state == "proof_matched":
            row["ready"] = True
            row["has_shot"] = True
            row["has_video"] = bool(deal.video_path) or not deal.needs_video
            row["hint"] = "готово к отправке"
            ready_count += 1
        elif state == "awaiting_proof":
            match = by_order.get(deal.order_id)
            if match is not None:
                row["has_shot"] = True
                row["file_name"] = match.receipt.path.name
                if deal.needs_video:
                    row["has_video"] = video_path is not None
                    if video_path is not None:
                        row["ready"] = True
                        row["hint"] = "чек и видео готовы"
                        ready_count += 1
                    else:
                        row["hint"] = "чек есть, ждём видео"
                else:
                    row["ready"] = True
                    row["has_video"] = False
                    row["hint"] = "чек найден"
                    ready_count += 1
            else:
                if deal.needs_video and video_path is None:
                    row["hint"] = "нужны чек и видео"
                elif deal.needs_video:
                    row["has_video"] = True
                    row["hint"] = "видео есть, ждём чек"
                else:
                    row["hint"] = "ждём чек"
            row["can_rescan"] = False
        deals_ui.append(row)

    unmatched = [
        r.path.name
        for r in receipts
        if str(r.path.resolve()) not in matched_paths
    ]
    awaiting_rows = [r for r in deals_ui if r["state"] == "awaiting_proof"]
    awaiting_ready = sum(1 for r in awaiting_rows if r["ready"])
    return {
        "ok": True,
        "folder": str(downloads_dir),
        "files_found": len(receipts),
        "video_ready": video_path is not None,
        "video_name": video_path.name if video_path is not None else "",
        "ready_count": awaiting_ready,
        "awaiting_count": len(awaiting_rows),
        "total": len(session.deals),
        "all_ready": bool(awaiting_rows) and awaiting_ready == len(awaiting_rows),
        "deals": deals_ui,
        "unmatched_files": unmatched[:8],
    }


def clear_deal_for_rescan(
    session: CompletionSession, order_id: str
) -> SessionDeal | None:
    """Сбросить привязку чека — можно положить новый файл и снова «Загрузить»."""
    deal = next((d for d in session.deals if d.order_id == order_id), None)
    if deal is None:
        return None
    if deal.state not in (
        DealCompletionState.FAILED,
        DealCompletionState.AWAITING_PROOF,
        DealCompletionState.PROOF_MATCHED,
    ):
        return None
    if deal.proof_path:
        try:
            session.used_proofs.discard(str(Path(deal.proof_path).resolve()))
        except OSError:
            session.used_proofs.discard(deal.proof_path)
    if deal.video_path:
        try:
            session.used_videos.discard(str(Path(deal.video_path).resolve()))
        except OSError:
            session.used_videos.discard(deal.video_path)
    deal.proof_path = ""
    deal.video_path = ""
    deal.error = ""
    deal.state = DealCompletionState.AWAITING_PROOF
    return deal


def apply_matches(
    session: CompletionSession,
    matches: list[ProofMatch],
    *,
    video_path: Path | None = None,
) -> None:
    for match in matches:
        deal = match.deal
        deal.proof_path = str(match.receipt.path)
        attach = video_path is not None and deal.needs_video
        deal.video_path = str(video_path) if attach else ""
        deal.state = DealCompletionState.PROOF_MATCHED
        video_hint = f" + {video_path.name}" if attach else ""
        mode = "чек+видео" if attach else "только чек"
        info(
            f"Совпадение #{deal.index} {_card_tag(deal.account_digits)} "
            f"← {match.receipt.path.name}{video_hint} "
            f"(карта {match.receipt.recipient_card}, {mode}, "
            f"{deal.amount_usdt:g} USDT)"
        )


async def _complete_one_matched_deal(
    deal: SessionDeal,
    *,
    session: CompletionSession,
    timing: HumanTiming,
    fake_money_sent: bool,
    page_by_order: dict[str, Page],
) -> None:
    """Одна сделка: upload + Money sent + Confirmed. Ошибка → FAILED + UI retry."""
    proof = Path(deal.proof_path or "")
    if not proof.is_file():
        deal.state = DealCompletionState.FAILED
        deal.error = f"чек не найден: {proof}"
        error(f"#{deal.index}: файл чека не найден")
        notify_completion_progress(
            session,
            phase="processing",
            message=f"Ошибка у сделки #{deal.index}",
            active_index=deal.index,
        )
        return

    video: Path | None = None
    if deal.video_path:
        video = Path(deal.video_path)
        if not video.is_file():
            deal.state = DealCompletionState.FAILED
            deal.error = f"видео не найдено: {video}"
            error(f"#{deal.index}: файл видео не найден")
            notify_completion_progress(
                session,
                phase="processing",
                message=f"Ошибка у сделки #{deal.index}",
                active_index=deal.index,
            )
            return

    page = page_by_order.get(deal.order_id)
    if page is None or page.is_closed():
        deal.state = DealCompletionState.FAILED
        deal.error = "вкладка PlatCore закрыта"
        error(f"#{deal.index}: вкладка PlatCore закрыта")
        notify_completion_progress(
            session,
            phase="processing",
            message=f"Ошибка у сделки #{deal.index}",
            active_index=deal.index,
        )
        return

    notify_completion_progress(
        session,
        phase="processing",
        message=(
            f"Загружаю чек+видео #{deal.index}…"
            if video is not None
            else f"Загружаю чек #{deal.index}…"
        ),
        active_index=deal.index,
    )

    raise_if_stopped()
    try:
        await ensure_dropzone_on_page(page)

        def _progress(msg: str, *, _idx: int = deal.index) -> None:
            notify_completion_progress(
                session,
                phase="processing",
                message=f"#{_idx}: {msg}",
                active_index=_idx,
            )

        result = await asyncio.wait_for(
            complete_deal_on_platcore(
                page,
                proof,
                timing=timing,
                fake_money_sent=fake_money_sent,
                deal_index=deal.index,
                account_digits=deal.account_digits,
                video_path=video,
                on_progress=_progress,
            ),
            timeout=2400.0 if video is not None else 300.0,
        )
        deal.state = DealCompletionState.COMPLETED
        deal.error = ""
        how = {
            "confirmed": "Confirmed",
            "gone": "модалка закрылась",
        }.get(result or "", "ok")
        ok(
            f"#{deal.index} {_card_tag(deal.account_digits)} — "
            f"отправка подтверждена ({how})"
        )
        notify_completion_progress(
            session,
            phase="processing",
            message=f"Чек #{deal.index} подтверждён ({how})",
        )
    except JobStopped:
        raise
    except Exception as exc:
        deal.state = DealCompletionState.FAILED
        deal.error = str(exc)
        error(f"#{deal.index}: {exc}")
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"Ошибка #{deal.index} — Повторить или Отмена",
            active_index=deal.index,
            allow_cancel=True,
        )


async def complete_matched_deals(
    session: CompletionSession,
    *,
    timing: HumanTiming,
    fake_money_sent: bool,
    page_by_order: dict[str, Page],
) -> None:
    ready = [
        d
        for d in session.deals
        if d.state == DealCompletionState.PROOF_MATCHED and d.proof_path
    ]
    if not ready:
        return

    n = len(ready)
    cards = ", ".join(_card_tag(d.account_digits) for d in ready)
    info(f"Параллельная загрузка {n} чек(ов): {cards}")
    notify_completion_progress(
        session,
        phase="processing",
        message=f"Загружаю {n} чек(ов) параллельно…",
    )

    tasks = [
        asyncio.create_task(
            _complete_one_matched_deal(
                deal,
                session=session,
                timing=timing,
                fake_money_sent=fake_money_sent,
                page_by_order=page_by_order,
            ),
            name=f"complete-{deal.index}",
        )
        for deal in ready
    ]

    try:
        await asyncio.gather(*tasks)
    except JobStopped:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except Exception:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    done = sum(1 for d in ready if d.state == DealCompletionState.COMPLETED)
    failed = sum(1 for d in ready if d.state == DealCompletionState.FAILED)
    info(f"Параллельная пачка: ok={done}, fail={failed}, всего={n}")
    if failed:
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"Ошибки загрузки: {failed} — у сделки «Повторить»",
            allow_cancel=True,
        )


def _scan_receipts_all_folders(
    session: CompletionSession,
    *,
    cfg: dict | None,
    screens_dir: Path,
    downloads_dir: Path,
) -> list[ReceiptParseResult]:
    """Чеки из СКРИНЫ и Downloads (если папки разные)."""
    receipts = scan_proof_files(session, cfg=cfg, folder=screens_dir)
    if screens_dir.resolve() == downloads_dir.resolve():
        return receipts
    seen = {str(r.path.resolve()) for r in receipts}
    for parsed in scan_proof_files(session, cfg=cfg, folder=downloads_dir):
        key = str(parsed.path.resolve())
        if key in seen:
            continue
        receipts.append(parsed)
        seen.add(key)
    return receipts


async def scan_and_complete_once(
    session: CompletionSession,
    *,
    timing: HumanTiming,
    fake_money_sent: bool,
    page_by_order: dict[str, Page],
    cfg: dict | None = None,
) -> int:
    """Один скан: ≤video_min_usdt — только чек; больше — чек+видео."""
    screens_dir = proofs_dir(cfg)
    downloads_dir = videos_dir(cfg)
    threshold = float(session.video_min_usdt)

    awaiting = [
        d for d in session.deals if d.state == DealCompletionState.AWAITING_PROOF
    ]
    skipped_n = sum(
        1 for d in session.deals if d.state == DealCompletionState.SKIPPED
    )
    # Нечего матчить — не сканим папку и не пишем «чеки есть»
    if not awaiting:
        session.cancel_unlocked = True
        if skipped_n:
            notify_completion_progress(
                session,
                phase="waiting",
                message=f"пропуск — Отмена ({skipped_n})",
                allow_cancel=True,
            )
        return 0

    large_awaiting = [d for d in awaiting if d.needs_video]
    video_path: Path | None = None
    if large_awaiting:
        video_path = pick_latest_video(
            since_ts=session.watch_started_at,
            used_paths=session.used_videos,
            cfg=cfg,
            folder=downloads_dir,
        )
        if video_path is None:
            warn(
                f"Крупные сделки (>{threshold:g} USDT) ждут видео в "
                f"{downloads_dir}"
            )
        else:
            info(f"Видео для крупных: {video_path.name} ← {downloads_dir}")

    # Крупные без видео не матчим — чек не «съедаем»
    candidates = [
        d
        for d in awaiting
        if (not d.needs_video) or (video_path is not None)
    ]

    receipts = _scan_receipts_all_folders(
        session,
        cfg=cfg,
        screens_dir=screens_dir,
        downloads_dir=downloads_dir,
    )
    matches = match_proofs_to_deals(session, receipts, candidates=candidates)
    if matches:
        apply_matches(session, matches, video_path=video_path)
        used_video = any(m.deal.needs_video for m in matches)
        if used_video and video_path is not None:
            session.used_videos.add(str(video_path.resolve()))
        with_video = sum(1 for m in matches if m.deal.needs_video)
        only_shot = len(matches) - with_video
        parts = [f"найдено чеков: {len(matches)}"]
        if only_shot:
            parts.append(f"только скрин: {only_shot}")
        if with_video:
            parts.append(f"чек+видео: {with_video}")
        notify_completion_progress(
            session,
            phase="processing",
            message="; ".join(parts),
        )
    elif receipts:
        info("Новые чеки есть, но совпадений по карте нет")
        notify_completion_progress(
            session,
            phase="processing",
            message="В папке есть файлы, но карты не совпали",
        )
    elif large_awaiting and video_path is None:
        notify_completion_progress(
            session,
            phase="waiting",
            message=(
                f"Крупные (>{threshold:g} USDT) ждут видео в "
                f"{downloads_dir.name}"
            ),
        )

    await complete_matched_deals(
        session,
        timing=timing,
        fake_money_sent=fake_money_sent,
        page_by_order=page_by_order,
    )
    # После скана+обработки: Отмена только у сделок без чека
    session.cancel_unlocked = True
    still_awaiting = [
        d
        for d in session.deals
        if d.state == DealCompletionState.AWAITING_PROOF
    ]
    failed_n = sum(
        1 for d in session.deals if d.state == DealCompletionState.FAILED
    )
    skipped_n = sum(
        1 for d in session.deals if d.state == DealCompletionState.SKIPPED
    )
    if still_awaiting or failed_n or skipped_n:
        parts: list[str] = []
        need_video = [d for d in still_awaiting if d.needs_video]
        need_shot = [d for d in still_awaiting if not d.needs_video]
        if need_shot:
            parts.append(f"ждут чек ({len(need_shot)})")
        if need_video:
            parts.append(
                f"ждут чек+видео (>{threshold:g} USDT, {len(need_video)})"
            )
        if failed_n:
            parts.append(f"ошибка — Повторить ({failed_n})")
        if still_awaiting:
            parts.append("без файла — Отмена")
        if skipped_n:
            parts.append(f"пропуск — Отмена ({skipped_n})")
        notify_completion_progress(
            session,
            phase="waiting",
            message="; ".join(parts),
            allow_cancel=True,
        )
    return len(matches)


async def cancel_deal_on_platcore(
    session: CompletionSession,
    order_id: str,
    *,
    timing: HumanTiming,
    page_by_order: dict[str, Page],
    cfg: dict,
) -> None:
    """Ручная отмена одной сделки (dispute без чека). Последовательно."""
    deal = next((d for d in session.deals if d.order_id == order_id), None)
    if deal is None:
        warn(f"Отмена: сделка order_id={order_id!r} не найдена")
        return
    if deal.state not in (
        DealCompletionState.AWAITING_PROOF,
        DealCompletionState.FAILED,
        DealCompletionState.SKIPPED,
    ):
        warn(
            f"#{deal.index}: отмена недоступна (state={deal.state.value})"
        )
        return

    page = page_by_order.get(deal.order_id)
    if page is None or page.is_closed():
        deal.state = DealCompletionState.FAILED
        deal.error = "вкладка PlatCore закрыта — отмена невозможна"
        error(f"#{deal.index}: вкладка закрыта, отмена не выполнена")
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"#{deal.index}: вкладка закрыта",
            allow_cancel=True,
        )
        return

    dispute = parse_dispute_config(cfg)
    notify_completion_progress(
        session,
        phase="processing",
        message=f"Отмена #{deal.index}…",
        active_index=deal.index,
        allow_cancel=False,
    )

    try:
        await ensure_dropzone_on_page(page)
        await asyncio.wait_for(
            submit_dispute_without_proof(
                page,
                dispute,
                timing=timing,
                deal_index=deal.index,
            ),
            timeout=180.0,
        )
        deal.state = DealCompletionState.CANCELLED
        deal.error = ""
        ok(f"#{deal.index} {_card_tag(deal.account_digits)} — отменена (dispute)")
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"#{deal.index} отменена",
            allow_cancel=True,
        )
    except JobStopped:
        raise
    except Exception as exc:
        deal.state = DealCompletionState.FAILED
        deal.error = str(exc)
        error(f"#{deal.index} отмена: {exc}")
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"#{deal.index}: ошибка отмены — Повторить или Отмена",
            allow_cancel=True,
            active_index=deal.index,
        )


async def retry_deal_money_sent(
    session: CompletionSession,
    order_id: str,
    *,
    timing: HumanTiming,
    fake_money_sent: bool,
    page_by_order: dict[str, Page],
) -> None:
    """Повтор Money sent для FAILED с уже найденным чеком."""
    deal = next((d for d in session.deals if d.order_id == order_id), None)
    if deal is None:
        warn(f"Retry: сделка order_id={order_id!r} не найдена")
        return
    if deal.state != DealCompletionState.FAILED or not deal.proof_path:
        warn(
            f"#{getattr(deal, 'index', '?')}: retry недоступен "
            f"(state={getattr(deal, 'state', None)})"
        )
        return

    deal.state = DealCompletionState.PROOF_MATCHED
    deal.error = ""
    info(f"#{deal.index}: повторная загрузка чека…")
    await _complete_one_matched_deal(
        deal,
        session=session,
        timing=timing,
        fake_money_sent=fake_money_sent,
        page_by_order=page_by_order,
    )
    if deal.state == DealCompletionState.FAILED:
        notify_completion_progress(
            session,
            phase="waiting",
            message=f"#{deal.index}: снова ошибка — Повторить или Отмена",
            allow_cancel=True,
            active_index=deal.index,
        )
    else:
        notify_completion_progress(
            session,
            phase="waiting",
            message=(
                f"#{deal.index} ок"
                if deal.state == DealCompletionState.COMPLETED
                else f"Статус #{deal.index}: {deal.state.value}"
            ),
            allow_cancel=True,
        )


async def run_completion_phase(
    context: BrowserContext,
    cfg: dict,
    *,
    accepted_deals: list[AcceptedDeal],
    page_by_order: dict[str, Page],
) -> None:
    del context

    comp_cfg = completion_settings(cfg)
    if not comp_cfg.get("enabled", True):
        info("Фаза чеков отключена в config")
        return

    if not accepted_deals:
        info("Нет принятых сделок — фаза чеков пропущена")
        return

    grace_sec = float(comp_cfg.get("watch_grace_sec", 5.0))
    video_min_usdt = float(comp_cfg.get("video_min_usdt", 225.0))
    session = build_session(
        accepted_deals,
        grace_sec=grace_sec,
        video_min_usdt=video_min_usdt,
    )
    set_active_completion_session(session, cfg)
    try:
        await _run_completion_phase_body(
            session=session,
            cfg=cfg,
            page_by_order=page_by_order,
            video_min_usdt=video_min_usdt,
        )
    finally:
        set_active_completion_session(None, None)


async def _run_completion_phase_body(
    *,
    session: CompletionSession,
    cfg: dict,
    page_by_order: dict[str, Page],
    video_min_usdt: float,
) -> None:
    timing = parse_human_timing(cfg)
    fake_money_sent = bool((cfg.get("stage2") or {}).get("fake_money_sent", False))
    downloads_dir = videos_dir(cfg)
    grace_sec = float(completion_settings(cfg).get("watch_grace_sec", 5.0))

    open_tabs = sum(
        1
        for d in session.deals
        if d.order_id in page_by_order
        and not page_by_order[d.order_id].is_closed()
    )
    n_skipped = sum(
        1 for d in session.deals if d.state == DealCompletionState.SKIPPED
    )
    awaiting = [
        d
        for d in session.deals
        if d.state == DealCompletionState.AWAITING_PROOF
    ]
    n_video = sum(1 for d in awaiting if d.needs_video)
    n_shot = len(awaiting) - n_video

    section(f"Чеки: {len(session.deals)} сделок, вкладок {open_tabs}")
    info(f"Папка: {downloads_dir}")
    if awaiting:
        info(
            f"Порог видео: >{video_min_usdt:g} USDT "
            f"(только чек: {n_shot}, чек+видео: {n_video})"
        )
        info(f"Ждём новые файлы (игнор старых {grace_sec:g} с)")
        info("После скана: без чека — «Отмена»; ошибка с чеком — «Повторить»")
    if n_skipped:
        info(f"Пропуск банка: {n_skipped} — серые, можно «Отмена»")
    print_session_status(session)
    if awaiting and n_skipped:
        start_msg = (
            f"Ожидание загрузки чеков. Пропуск ({n_skipped}) — нажмите «Отмена»"
        )
    elif n_skipped and not awaiting:
        start_msg = (
            f"Нужно отменить пропуски ({n_skipped})"
        )
    else:
        n_wait = len(awaiting) or len(session.deals)
        start_msg = f"Ожидание загрузки чеков ({n_wait})"
    notify_completion_progress(
        session,
        phase="waiting",
        message=start_msg,
        allow_cancel=True,
    )

    while session.unresolved():
        raise_if_stopped()
        remaining = session.unresolved()
        awaiting = [
            d for d in remaining if d.state == DealCompletionState.AWAITING_PROOF
        ]
        skipped = [
            d for d in remaining if d.state == DealCompletionState.SKIPPED
        ]
        if skipped and not awaiting:
            wait_msg = (
                f"Нужно отменить пропуски ({len(skipped)})"
            )
            confirm_hint = (
                f"Нужно отменить пропуски ({len(skipped)})"
            )
        elif session.cancel_unlocked and awaiting:
            wait_msg = (
                f"Ожидание загрузки чеков ({len(remaining)})"
            )
            confirm_hint = (
                f"Ожидание загрузки чеков ({len(remaining)})"
            )
        else:
            extra = f", пропуск {len(skipped)}" if skipped else ""
            wait_msg = (
                f"Ожидание загрузки чеков ({len(remaining)}{extra})"
            )
            confirm_hint = (
                f"Ожидание загрузки чеков ({len(remaining)}{extra})"
            )
        notify_completion_progress(
            session,
            phase="waiting",
            message=wait_msg,
            allow_cancel=True,
        )
        confirm_kind = await wait_user_confirm(confirm_hint)
        raise_if_stopped()

        kind = (confirm_kind or "receipts").strip().lower()
        if kind.startswith("cancel:"):
            order_id = kind.split(":", 1)[1].strip()
            await cancel_deal_on_platcore(
                session,
                order_id,
                timing=timing,
                page_by_order=page_by_order,
                cfg=cfg,
            )
            print_session_status(session)
            continue

        if kind.startswith("retry:rescan:"):
            order_id = kind.split(":", 2)[2].strip()
            cleared = clear_deal_for_rescan(session, order_id)
            if cleared is None:
                warn(f"Новый файл: сделка {order_id!r} недоступна")
            else:
                info(
                    f"#{cleared.index}: сброшен чек — положи новый файл "
                    f"и нажми «Загрузить»"
                )
                notify_completion_progress(
                    session,
                    phase="waiting",
                    message=(
                        f"#{cleared.index} {_card_tag(cleared.account_digits)}: "
                        f"положи новый файл → «Загрузить»"
                    ),
                    allow_cancel=True,
                )
            print_session_status(session)
            continue

        if kind.startswith("retry:"):
            order_id = kind.split(":", 1)[1].strip()
            await retry_deal_money_sent(
                session,
                order_id,
                timing=timing,
                fake_money_sent=fake_money_sent,
                page_by_order=page_by_order,
            )
            print_session_status(session)
            continue

        notify_completion_progress(
            session,
            phase="processing",
            message="Сканирую папку и загружаю…",
            allow_cancel=False,
        )
        await scan_and_complete_once(
            session,
            timing=timing,
            fake_money_sent=fake_money_sent,
            page_by_order=page_by_order,
            cfg=cfg,
        )
        print_session_status(session)

    done = session.completed_count()
    cancelled = session.cancelled_count()
    failed = sum(1 for d in session.deals if d.state == DealCompletionState.FAILED)
    if failed:
        msg = (
            f"Готово: {done}/{len(session.deals)}"
            + (f", отмен: {cancelled}" if cancelled else "")
            + f", ошибок: {failed}"
        )
    elif cancelled:
        msg = (
            f"Готово: {done}/{len(session.deals)} "
            f"(чеки + отмены {cancelled})"
        )
    else:
        msg = f"Все {len(session.deals)} чеков загружены успешно"
    notify_completion_progress(session, phase="done", message=msg)
    ok(f"Фаза чеков завершена ({done}/{len(session.deals)})")
    pipe_cfg = cfg.get("pipeline") or {}
    if not pipe_cfg.get("exit_after_run", True):
        info("Браузер останется открытым до следующего запуска (exit_after_run=false)")
