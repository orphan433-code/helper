"""Сделки Alif без чека. Не держат цикл: отмена или поздний скрин — руками."""

from __future__ import annotations

import json
import time
from typing import Any

from pathlib import Path

from core.paths import RUNTIME_DIR

_PATH = RUNTIME_DIR / "alif_waiting.json"

IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".heic",
    ".heif",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}
VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".3gp",
    ".3gpp",
    ".avi",
    ".mpeg",
    ".mpg",
    ".qt",
}


def classify_proof(name: str, content_type: str = "") -> str:
    """image | video | other. Сначала расширение, потом MIME."""
    suffix = Path(name or "").suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in VIDEO_EXTS:
        return "video"
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype.startswith("image/"):
        return "image"
    if ctype.startswith("video/"):
        return "video"
    return "other"


def split_proof_files(items: list[tuple[str, str]]) -> tuple[int, int] | str:
    """Индексы (чек, видео или -1). Иначе текст ошибки."""
    if not items or len(items) > 2:
        return "Выбери 1 или 2 файла"
    kinds = [classify_proof(name, ctype) for name, ctype in items]
    if any(kind == "other" for kind in kinds):
        bad = [items[i][0] or "файл" for i, kind in enumerate(kinds) if kind == "other"]
        return f"Не понял формат: {', '.join(bad)}"
    images = [i for i, kind in enumerate(kinds) if kind == "image"]
    videos = [i for i, kind in enumerate(kinds) if kind == "video"]
    if len(images) != 1:
        return "Нужен один скрин чека"
    if len(videos) > 1:
        return "Нужно одно видео"
    return images[0], videos[0] if videos else -1


def _load() -> list[dict[str, Any]]:
    if not _PATH.is_file():
        return []
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict) and row.get("order_id")]


def _save(rows: list[dict[str, Any]]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_waiting() -> list[dict[str, Any]]:
    return _load()


def clear_waiting() -> None:
    """Старт сервиса сбрасывает очередь. Иначе после рестарта сделки снова висят."""
    _save([])


def get_waiting(order_id: str) -> dict[str, Any] | None:
    oid = str(order_id or "").strip()
    for row in _load():
        if str(row.get("order_id") or "") == oid:
            return row
    return None


def park_waiting(record: dict[str, Any]) -> dict[str, Any]:
    oid = str(record.get("order_id") or "").strip()
    if not oid:
        raise ValueError("alif waiting: нет order_id")
    rows = [row for row in _load() if str(row.get("order_id") or "") != oid]
    stored = dict(record)
    stored["order_id"] = oid
    stored["parked_at"] = time.time()
    rows.append(stored)
    _save(rows)
    return stored


def drop_waiting(order_id: str) -> dict[str, Any] | None:
    oid = str(order_id or "").strip()
    rows = _load()
    kept: list[dict[str, Any]] = []
    found: dict[str, Any] | None = None
    for row in rows:
        if str(row.get("order_id") or "") == oid and found is None:
            found = row
            continue
        kept.append(row)
    if found is not None:
        _save(kept)
    return found
