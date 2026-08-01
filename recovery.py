"""Обработка критических ошибок: продолжить / повторить / выйти."""

from __future__ import annotations

from typing import Any, Literal

from job_control import JobStopped
from logkit import info, warn
from user_prompts import ask_recovery_choice

RecoveryChoice = Literal["continue", "exit", "retry"]


def _stage_label(stage: str, deal_index: int | None) -> str:
    labels = {
        "банк": "Ошибка в банковском приложении",
        "PlatCore Accept": "Ошибка приёма сделки на PlatCore",
        "чек / Money sent": "Ошибка при отправке чека (Money sent)",
    }
    base = labels.get(stage, f"Ошибка: {stage}")
    if deal_index is not None:
        return f"{base} · сделка #{deal_index}"
    return base


def deal_summary_from_accepted(accepted: Any) -> dict[str, Any]:
    """Краткие реквизиты для UI (AcceptedDeal)."""
    d = accepted.data
    digits = str(d["account"]["digits"])
    inp = d["amount_input"]
    ver = d["amount_verify"]
    return {
        "index": accepted.index,
        "card": digits,
        "card_short": f"*{digits[-4:]}" if len(digits) >= 4 else digits,
        "holder": str(d.get("holder_name") or "—"),
        "amount_tjs": f"{inp['value']:g} {inp['currency']}",
        "amount_target": f"{ver['value']:g} {ver['currency']}",
        "order_id": str(d.get("order_id") or accepted.order_id or ""),
    }


def deal_summary_from_session(deal: Any) -> dict[str, Any]:
    digits = str(deal.account_digits)
    return {
        "index": deal.index,
        "card": digits,
        "card_short": f"*{digits[-4:]}" if len(digits) >= 4 else digits,
        "holder": str(deal.holder_name or "—"),
        "amount_tjs": str(getattr(deal, "amount_tjs", "") or "—"),
        "amount_target": str(getattr(deal, "amount_target", "") or "—"),
        "order_id": str(deal.order_id or ""),
    }


def is_post_payment_error(exc: BaseException) -> bool:
    try:
        from bank_form import BankPostPaymentError

        if isinstance(exc, BankPostPaymentError):
            return True
    except ImportError:
        pass
    text = str(exc).lower()
    return "на главную" in text and (
        "не появилась" in text or "не видит" in text or "оплата уже" in text
    )


async def offer_recovery_choice(
    exc: BaseException,
    *,
    stage: str,
    deal_index: int | None = None,
    summary: dict[str, Any] | None = None,
    allow_retry: bool = False,
) -> RecoveryChoice:
    """
    Показать ошибку в UI и ждать выбор.

    continue — пропустить сделку / шаг (или продолжить после post-payment)
    retry    — повторить тот же шаг (банк, Money sent)
    exit     — остановить весь цикл (JobStopped)
    """
    post_paid = is_post_payment_error(exc)
    if post_paid:
        allow_retry = False
        title = "Оплата прошла, но не удалось нажать «На главную»"
        if deal_index is not None:
            title = f"{title} · сделка #{deal_index}"
        detail = (
            "Перевод в банке уже выполнен. Повторять шаг нельзя — будет вторая оплата. "
            "Вернись на главную вручную на телефоне, затем нажми «Продолжить»."
        )
        extra = str(exc).strip()
        if extra:
            detail = f"{detail}\n\nТехнически: {extra}"
    else:
        title = _stage_label(stage, deal_index)
        detail = str(exc).strip() or exc.__class__.__name__

    ui_summary = dict(summary or {})
    if post_paid:
        ui_summary["payment_done"] = True
        ui_summary["continue_label"] = "Продолжить"

    hint = _hint_for(
        exc, stage, allow_retry=allow_retry, payment_done=post_paid
    )

    choice = await ask_recovery_choice(
        title,
        detail=detail,
        hint=hint,
        summary=ui_summary,
        allow_retry=allow_retry,
    )

    if choice == "exit":
        raise JobStopped(f"Остановлено пользователем: {detail}")
    if choice == "retry":
        info(f"{title}: повтор после исправления")
        return "retry"
    if post_paid:
        info(f"{title}: продолжаем (оплата уже была)")
    else:
        warn(f"{title}: пропуск")
    return "continue"


def _hint_for(
    exc: BaseException,
    stage: str,
    *,
    allow_retry: bool,
    payment_done: bool = False,
) -> str:
    text = str(exc).lower()
    lines: list[str] = []

    if payment_done:
        lines.append(
            "Деньги уже ушли. Не жми повтор перевода — только вернись на главную "
            "в приложении банка, затем продолжай."
        )
        lines.append("")
        lines.append("• Продолжить — считать перевод успешным и идти дальше")
        lines.append("• Остановить обработку — полностью прервать запуск")
        return "\n".join(lines)

    if "eur" in text or "usd" in text or "сумм" in text or "зачислен" in text:
        lines.append(
            "Сумма в банке не совпала с ожидаемой. "
            "Проверьте баланс и курс, исправьте на телефоне."
        )
    elif stage == "банк":
        lines.append(
            "Не удалось выполнить перевод: баланс, реквизиты, OCR или клик. "
            "Исправьте в банковском приложении на телефоне."
        )
    elif stage.startswith("PlatCore"):
        if any(
            x in text
            for x in (
                "уже",
                "дубл",
                "already",
                "duplicate",
                "оплач",
                "занят",
            )
        ):
            lines.append(
                "Платформа отклонила Accept (сделка/реквизиты уже заняты). "
                "Тост мог перекрыть кнопки — после пропуска цикл пойдёт дальше."
            )
        else:
            lines.append(
                "Не удалось принять сделку на PlatCore. "
                "Проверьте браузер и список сделок."
            )
    elif stage.startswith("чек"):
        lines.append(
            "Не удалось отправить чек или нажать Money sent. "
            "Проверьте вкладку PlatCore и файл чека."
        )

    lines.append("")
    if allow_retry:
        lines.append(
            "• Повторить этот шаг — выполнить операцию заново для той же сделки"
        )
    lines.append("• Пропустить сделку — отменить текущую и перейти к следующей")
    lines.append("• Остановить обработку — полностью прервать запуск")

    return "\n".join(lines)
