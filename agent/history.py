"""Кеш разобранных AI-команд — повтор без Gemini."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from core.paths import RUNTIME_DIR

HISTORY_PATH = RUNTIME_DIR / "agent_history.json"
MAX_ENTRIES = 80
_lock = threading.Lock()

_WS_RE = re.compile(r"\s+")


def normalize_command(text: str) -> str:
    """Ключ кеша: lower + схлопнутые пробелы."""
    return _WS_RE.sub(" ", str(text or "").strip().lower())


def _empty() -> dict[str, Any]:
    return {"version": 1, "entries": []}


def _load() -> dict[str, Any]:
    path = HISTORY_PATH
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    return data


def _save(data: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(HISTORY_PATH)


def lookup(text: str) -> dict[str, Any] | None:
    """Найти запись по нормализованному тексту команды."""
    key = normalize_command(text)
    if not key:
        return None
    with _lock:
        data = _load()
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("key") or "") == key:
                return dict(entry)
    return None


def touch(text: str) -> None:
    """Обновить hits / last_used при cache hit."""
    key = normalize_command(text)
    if not key:
        return
    now = time.time()
    with _lock:
        data = _load()
        entries: list[dict[str, Any]] = list(data.get("entries") or [])
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("key") or "") == key:
                entry["hits"] = int(entry.get("hits") or 0) + 1
                entry["last_used"] = now
                break
        entries.sort(key=lambda e: float(e.get("last_used") or 0), reverse=True)
        data["entries"] = entries
        _save(data)


def remember(
    text: str,
    plan: dict[str, Any],
    summary: str,
    *,
    source: str = "gemini",
) -> None:
    """Сохранить успешный разбор (или обновить существующий)."""
    key = normalize_command(text)
    cleaned = str(text or "").strip()
    if not key or not isinstance(plan, dict):
        return
    now = time.time()
    # В кеше — сырой plan без UI-merge аккаунтов (аккаунты подтянутся при hit)
    plan_store = dict(plan)
    with _lock:
        data = _load()
        entries: list[dict[str, Any]] = [
            e for e in (data.get("entries") or []) if isinstance(e, dict)
        ]
        found = False
        for entry in entries:
            if str(entry.get("key") or "") == key:
                entry["text"] = cleaned
                entry["plan"] = plan_store
                entry["summary"] = str(summary or "")
                entry["source"] = source
                entry["hits"] = int(entry.get("hits") or 0) + 1
                entry["last_used"] = now
                found = True
                break
        if not found:
            entries.insert(
                0,
                {
                    "key": key,
                    "text": cleaned,
                    "plan": plan_store,
                    "summary": str(summary or ""),
                    "source": source,
                    "hits": 1,
                    "created": now,
                    "last_used": now,
                },
            )
        entries.sort(key=lambda e: float(e.get("last_used") or 0), reverse=True)
        data["entries"] = entries[:MAX_ENTRIES]
        _save(data)


def list_history(limit: int = 30) -> list[dict[str, Any]]:
    """Недавние команды для UI (без полного plan — лёгкий список).

    Избранные первыми, затем по last_used.
    """
    lim = max(1, min(int(limit or 30), MAX_ENTRIES))
    with _lock:
        data = _load()
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        entries.sort(
            key=lambda e: (
                0 if e.get("favorite") else 1,
                -float(e.get("last_used") or 0),
            )
        )
        out: list[dict[str, Any]] = []
        for entry in entries:
            out.append(
                {
                    "text": str(entry.get("text") or ""),
                    "summary": str(entry.get("summary") or ""),
                    "hits": int(entry.get("hits") or 0),
                    "last_used": float(entry.get("last_used") or 0),
                    "source": str(entry.get("source") or ""),
                    "favorite": bool(entry.get("favorite")),
                }
            )
            if len(out) >= lim:
                break
        return out


def set_favorite(text: str, favorite: bool) -> bool:
    """Пометить команду избранной / снять пометку."""
    key = normalize_command(text)
    if not key:
        return False
    with _lock:
        data = _load()
        entries: list[dict[str, Any]] = list(data.get("entries") or [])
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("key") or "") == key:
                entry["favorite"] = bool(favorite)
                data["entries"] = entries
                _save(data)
                return True
        return False


def clear_history(*, keep_favorites: bool = True) -> int:
    """Очистить кеш. По умолчанию избранные остаются. Вернуть сколько удалено."""
    with _lock:
        data = _load()
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        if keep_favorites:
            kept = [e for e in entries if e.get("favorite")]
            removed = len(entries) - len(kept)
            data["entries"] = kept
            _save(data)
            return removed
        n = len(entries)
        _save(_empty())
        return n


def remove_entry(text: str) -> bool:
    key = normalize_command(text)
    if not key:
        return False
    with _lock:
        data = _load()
        before = data.get("entries") or []
        after = [
            e
            for e in before
            if isinstance(e, dict) and str(e.get("key") or "") != key
        ]
        if len(after) == len(before):
            return False
        data["entries"] = after
        _save(data)
        return True
