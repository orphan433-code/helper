"""Сохранение скринов успешного перевода для PlatCore."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from bank_confirm import is_transfer_success_screen
from bank_receipt import is_success_receipt, parse_receipt_image
from bank_screen import scan_screen
from completion_registry import attach_proof, proofs_dir, videos_dir
from config_loader import capture_region_or_raise, completion_settings
from deal_bridge import PENDING_DEAL_PATH
from screenshot import take_screenshot


def _pending_meta() -> dict:
    if not PENDING_DEAL_PATH.exists():
        return {}
    try:
        payload = json.loads(PENDING_DEAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_proof_image(
    image: Image.Image,
    *,
    account_digits: str,
    order_id: str = "",
    cfg: dict | None = None,
) -> Path:
    out_dir = proofs_dir(cfg)
    last4 = account_digits[-4:] if len(account_digits) >= 4 else "xxxx"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    oid = (order_id or "deal")[:12]
    path = out_dir / f"{stamp}_{oid}_{last4}.png"
    image.save(path)
    return path


def capture_success_proof_from_mirror(
    *,
    account_digits: str | None = None,
    order_id: str | None = None,
    cfg: dict | None = None,
) -> Path | None:
    """Скрин текущего экрана Android, если это «Детали перевода»."""
    comp = completion_settings(cfg)
    if not comp.get("enabled", True):
        return None

    meta = _pending_meta()
    account = account_digits or str(meta.get("account") or "").strip()
    oid = order_id or str(meta.get("order_id") or "").strip()
    if not account:
        return None

    capture = capture_region_or_raise(cfg)
    hits = scan_screen(capture)
    cfg_confirm = {"success_screen_markers": ["Детали перевода"]}
    if not is_transfer_success_screen(hits, cfg_confirm):
        return None

    raw_text = "\n".join(hit.text for hit in hits)
    if comp.get("require_success_status", False) and not is_success_receipt(hits, raw_text):
        return None

    image = take_screenshot(region=capture)
    path = save_proof_image(image, account_digits=account, order_id=oid, cfg=cfg)
    if oid:
        attach_proof(oid, path, cfg=cfg)
    print(f"[Completion] Чек сохранён: {path.name}")
    return path


def save_success_proof_before_home(
    *,
    account_digits: str | None = None,
    order_id: str | None = None,
    cfg: dict | None = None,
) -> Path | None:
    """Вызывается из bank_confirm на экране успеха перед «На главную»."""
    comp = completion_settings(cfg)
    if not comp.get("save_proofs_on_success", True):
        return None
    return capture_success_proof_from_mirror(
        account_digits=account_digits,
        order_id=order_id,
        cfg=cfg,
    )


def validate_proof_file(path: Path) -> bool:
    parsed = parse_receipt_image(path)
    return bool(parsed.recipient_card)


_PROOF_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}


def _sync_from_phone(*, kind: str, since_ts: float) -> None:
    """Подтянуть новые файлы с телефона (ошибки глотаем — остаётся Downloads)."""
    try:
        from phone_media import pull_new_phone_media

        pull_new_phone_media(kind=kind, since_ts=since_ts)
    except Exception:
        pass


def _list_new_media_files(
    *,
    exts: set[str],
    folder: Path,
    since_ts: float = 0.0,
    used_paths: set[str] | None = None,
) -> list[Path]:
    used = {str(Path(p).resolve()) for p in (used_paths or set())}
    paths: list[Path] = []

    if not folder.is_dir():
        return paths

    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if path.name.startswith("."):
            continue
        resolved = str(path.resolve())
        if resolved in used:
            continue
        if since_ts and path.stat().st_mtime < since_ts:
            continue
        paths.append(path)

    return sorted(paths, key=lambda p: p.stat().st_mtime)


def list_new_proof_files(
    *,
    since_ts: float = 0.0,
    used_paths: set[str] | None = None,
    cfg: dict | None = None,
    folder: Path | None = None,
) -> list[Path]:
    """Скрины: Mac proofs_dir + pull новых с телефона в ту же папку."""
    _sync_from_phone(kind="screens", since_ts=since_ts)
    return _list_new_media_files(
        exts=_PROOF_EXTS,
        folder=folder if folder is not None else proofs_dir(cfg),
        since_ts=since_ts,
        used_paths=used_paths,
    )


def list_new_video_files(
    *,
    since_ts: float = 0.0,
    used_paths: set[str] | None = None,
    cfg: dict | None = None,
    folder: Path | None = None,
) -> list[Path]:
    """Видео: Mac videos_dir + pull новых с телефона в ту же папку."""
    _sync_from_phone(kind="videos", since_ts=since_ts)
    return _list_new_media_files(
        exts=_VIDEO_EXTS,
        folder=folder if folder is not None else videos_dir(cfg),
        since_ts=since_ts,
        used_paths=used_paths,
    )


def pick_latest_video(
    *,
    since_ts: float = 0.0,
    used_paths: set[str] | None = None,
    cfg: dict | None = None,
    folder: Path | None = None,
) -> Path | None:
    videos = list_new_video_files(
        since_ts=since_ts,
        used_paths=used_paths,
        cfg=cfg,
        folder=folder,
    )
    return videos[-1] if videos else None
