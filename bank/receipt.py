"""OCR чека «Детали перевода» — сверка по карте получателя."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from bank.confirm import is_transfer_success_screen
from bank.screen import find_labels
from core.config import completion_settings
from device.ocr import OcrHit

_MASKED_CARD_RE = re.compile(
    r"(\d{4,8})\s*[*•]{2,}\s*(\d{4})",
)
# Звёзды, точки, крестики — любая дырка в номере, бренд не важен.
_MASK_CHAR_RE = re.compile(r"[*•·∙●×xX]")
_CARD_DIGITS_RE = re.compile(r"\d{10,19}")
_SUCCESS_MARKERS = (
    "Операция завершена успешно",
    "завершена успешно",
    "успешно",
)
_RECIPIENT_CARD_LABELS = (
    "Карта получателя",
    "карта получателя",
    "Recipient card",
)
_ALIF_ACCOUNT_LABELS = (
    "Счёт зачисления",
    "Счет зачисления",
)


@dataclass(frozen=True)
class ReceiptParseResult:
    path: Path
    recipient_card: str
    success: bool
    raw_text: str
    prefix_digits: str
    last4: str


def _normalize_card_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _alif_card_parts(compact: str) -> tuple[str, str] | None:
    """Маска с дыркой: хвост 4 цифры, цифры в начале — если они есть.

    MCR**8307, VSA**1488, 4154***ANY**1636, ****8307. Бренд не список.
    Сумму «5918,07» и голый номер транзакции не берём: там нет дырки в номере.
    """
    from core.payout_bank import is_alif

    if not is_alif():
        return None
    if not compact or not _MASK_CHAR_RE.search(compact):
        return None
    tail = re.search(r"(\d{4})$", compact)
    if tail is None:
        return None
    head = compact[: tail.start()]
    prefix_match = re.match(r"(\d{4,8})", head)
    prefix = prefix_match.group(1) if prefix_match else ""
    return prefix, tail.group(1)


def extract_card_parts(text: str) -> tuple[str, str] | None:
    """Вернуть (prefix, last4) из маскированной или полной карты."""
    compact = _normalize_card_text(text)
    masked = _MASKED_CARD_RE.search(compact)
    if masked:
        return masked.group(1), masked.group(2)

    alif = _alif_card_parts(compact)
    if alif is not None:
        return alif

    digits = re.sub(r"\D", "", compact)
    if len(digits) >= 10:
        return digits[:-4], digits[-4:]
    return None


def cards_match(account_digits: str, receipt_card: str) -> bool:
    """Сверка по карте получателя (не по имени)."""
    deal_digits = re.sub(r"\D", "", account_digits or "")
    parts = extract_card_parts(receipt_card)
    if not parts or len(deal_digits) < 10:
        return False

    prefix, last4 = parts
    if not deal_digits.endswith(last4):
        return False
    # MCR**8307 — BIN на чеке нет, хватает хвоста.
    if not prefix or not prefix.isdigit():
        return True
    if deal_digits.startswith(prefix):
        return True
    if len(prefix) >= 6 and deal_digits.startswith(prefix[:6]):
        return True
    if len(prefix) >= 8 and deal_digits.startswith(prefix[:8]):
        return True
    return False


def _ocr_image(path: Path) -> tuple[list[OcrHit], str]:
    """OCR сохранённого скрина (полный кадр телефона)."""
    from ocrmac import ocrmac

    image = Image.open(path)
    img_w, img_h = image.size
    raw = ocrmac.OCR(
        image,
        language_preference=["ru-RU", "en-US"],
    ).recognize()

    hits: list[OcrHit] = []
    for text, confidence, bbox in raw:
        if confidence < 0.15:
            continue
        x, y, w, h = bbox
        px_left = x * img_w
        px_top = (1.0 - y - h) * img_h
        px_width = w * img_w
        px_height = h * img_h
        hits.append(
            OcrHit(
                text=str(text),
                confidence=float(confidence),
                x=px_left + px_width / 2,
                y=px_top + px_height / 2,
                width=px_width,
                height=px_height,
            )
        )

    raw_text = "\n".join(hit.text for hit in hits)
    return hits, raw_text


def _row_value(hits: list[OcrHit], label: OcrHit) -> str:
    """Текст справа от якоря, включая куски чуть ниже строки."""
    cells = [
        hit
        for hit in hits
        if hit is not label
        and hit.x >= label.x + 40
        and -12 <= (hit.y - label.y) <= 36
    ]
    return " ".join(hit.text for hit in sorted(cells, key=lambda hit: (hit.y, hit.x)))


def _recipient_labels() -> tuple[str, ...]:
    from core.payout_bank import is_alif

    if is_alif():
        return _ALIF_ACCOUNT_LABELS
    return _RECIPIENT_CARD_LABELS


def _find_recipient_card_in_hits(hits: list[OcrHit], raw_text: str) -> str:
    from core.payout_bank import is_alif

    label = find_labels(hits, list(_recipient_labels()), partial=True)
    if label is not None:
        # Alif: значение справа от «Счёт зачисления», маска какая угодно.
        if is_alif():
            cell = _row_value(hits, label)
            parts = _alif_card_parts(_normalize_card_text(cell))
            if parts:
                prefix, last4 = parts
                return f"{prefix}****{last4}"
        same_row = [
            hit
            for hit in hits
            if abs(hit.y - label.y) <= 28 and hit.x >= label.x - 20
        ]
        for hit in sorted(same_row, key=lambda h: h.x):
            parts = extract_card_parts(hit.text)
            if parts:
                prefix, last4 = parts
                return f"{prefix}****{last4}"
        below = [
            hit
            for hit in hits
            if label.y < hit.y <= label.y + 80 and hit.x >= label.x - 40
        ]
        for hit in sorted(below, key=lambda h: (h.y, -h.x)):
            parts = extract_card_parts(hit.text)
            if parts:
                prefix, last4 = parts
                return f"{prefix}****{last4}"

    for match in _MASKED_CARD_RE.finditer(_normalize_card_text(raw_text)):
        prefix, last4 = match.group(1), match.group(2)
        return f"{prefix}****{last4}"

    if is_alif():
        pay = find_labels(hits, ["Способ оплаты"], partial=True)
        for hit in sorted(hits, key=lambda h: h.y):
            if pay is not None and abs(hit.y - pay.y) <= 28:
                continue
            alif = _alif_card_parts(_normalize_card_text(hit.text))
            if alif is None:
                continue
            prefix, last4 = alif
            return f"{prefix}****{last4}"

    for match in _CARD_DIGITS_RE.finditer(raw_text):
        digits = match.group(0)
        if len(digits) >= 10:
            return digits
    return ""


def is_success_receipt(hits: list[OcrHit], raw_text: str) -> bool:
    from core.payout_bank import is_alif

    if is_alif():
        folded = raw_text.lower().replace("ё", "е")
        return "исполнено" in folded

    if is_transfer_success_screen(
        hits,
        {"success_screen_markers": ["Детали перевода"]},
    ):
        if find_labels(hits, list(_SUCCESS_MARKERS), partial=True) is not None:
            return True
        lowered = raw_text.lower()
        if "завершена успешно" in lowered or "операция завершена" in lowered:
            return True
    return False


def parse_receipt_image(path: Path, *, require_success: bool | None = None) -> ReceiptParseResult:
    if require_success is None:
        require_success = bool(completion_settings().get("require_success_status", True))

    hits, raw_text = _ocr_image(path)
    recipient_card = _find_recipient_card_in_hits(hits, raw_text)
    success = is_success_receipt(hits, raw_text)
    if require_success and not success:
        recipient_card = ""

    parts = extract_card_parts(recipient_card) if recipient_card else None
    prefix = parts[0] if parts else ""
    last4 = parts[1] if parts else ""

    return ReceiptParseResult(
        path=path.resolve(),
        recipient_card=recipient_card,
        success=success,
        raw_text=raw_text,
        prefix_digits=prefix,
        last4=last4,
    )
