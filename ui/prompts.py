"""Подтверждения пользователя — консоль или GUI."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

# Возвращает kind: "receipts" | "video" | иной (login и т.п.)
ConfirmHandler = Callable[[str], Awaitable[str]]
RecoveryChoice = Literal["continue", "exit", "retry"]
RecoveryHandler = Callable[
    [str, str, str, dict[str, Any], bool],
    Awaitable[RecoveryChoice],
]

_handler: ConfirmHandler | None = None
_recovery_handler: RecoveryHandler | None = None


def set_confirm_handler(handler: ConfirmHandler | None) -> None:
    global _handler
    _handler = handler


def set_recovery_handler(handler: RecoveryHandler | None) -> None:
    global _recovery_handler
    _recovery_handler = handler


def _normalize_confirm_kind(raw: str) -> str:
    """receipts/video — lower; cancel:/retry: — регистр order_id сохраняем."""
    kind = str(raw or "receipts").strip()
    if not kind:
        return "receipts"
    low = kind.lower()
    if low.startswith("retry:rescan:"):
        return "retry:rescan:" + kind.split(":", 2)[2].strip()
    if low.startswith("cancel:"):
        return "cancel:" + kind.split(":", 1)[1].strip()
    if low.startswith("retry:"):
        return "retry:" + kind.split(":", 1)[1].strip()
    return low


async def wait_user_confirm(prompt: str) -> str:
    """Ждёт подтверждение пользователя. kind: receipts | video."""
    if _handler is not None:
        kind = await _handler(prompt)
        return _normalize_confirm_kind(kind or "receipts")
    print(prompt, end="", flush=True)
    await asyncio.to_thread(input)
    print()
    return "receipts"

async def ask_recovery_choice(
    message: str,
    *,
    detail: str = "",
    hint: str = "",
    summary: dict[str, Any] | None = None,
    allow_retry: bool = False,
) -> RecoveryChoice:
    if _recovery_handler is not None:
        return await _recovery_handler(
            message,
            detail,
            hint,
            summary or {},
            allow_retry,
        )

    print(f"\n{'=' * 50}")
    print(f"ПРОБЛЕМА: {message}")
    if summary:
        print("Сделка:", json.dumps(summary, ensure_ascii=False))
    if detail:
        print(f"Детали: {detail}")
    if hint:
        print(hint)
    print("=" * 50)

    payment_done = bool((summary or {}).get("payment_done"))
    if payment_done:
        opts = "Продолжить (p) / Выйти (v)"
    elif not allow_retry:
        opts = "Пропустить (p) / Выйти (v)"
    else:
        opts = "Повторить (r) / Пропустить (p) / Выйти (v)"

    while True:
        answer = (
            await asyncio.to_thread(input, f"{opts}: ")
        ).strip().lower()
        if allow_retry and answer in ("r", "повтор", "retry", ""):
            return "retry"
        if answer in (
            "p", "пр", "пропустить", "continue", "c", "продолжить", "ok",
        ):
            return "continue"
        if answer in ("v", "в", "выйти", "exit", "q"):
            return "exit"
        if not allow_retry and answer == "":
            return "continue"
