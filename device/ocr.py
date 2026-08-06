"""OCR через ocrmac с координатами для adb tap."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from core.config import capture_region, ocr_settings
from device.screenshot import get_retina_scale, region_offset


@dataclass(frozen=True)
class OcrHit:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float
    inferred: bool = False


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def enrich_keypad_digits(hits: list[OcrHit]) -> list[OcrHit]:
    """
    Vision часто не видит часть цифр на PIN-клавиатуре (особенно Android).
    Достраиваем сетку 1–9 и 0 по геометрии видимых кнопок.
    """
    by_digit: dict[str, OcrHit] = {}
    for hit in hits:
        key = hit.text.strip()
        if key in ("O", "o"):
            key = "0"
        if len(key) == 1 and key.isdigit():
            by_digit[key] = hit

    ref = next((h for h in by_digit.values()), None)
    w = ref.width if ref else 40.0
    h = ref.height if ref else 40.0

    def xs(*digits: str) -> list[float]:
        return [by_digit[d].x for d in digits if d in by_digit]

    def ys(*digits: str) -> list[float]:
        return [by_digit[d].y for d in digits if d in by_digit]

    x_left = _avg(xs("1", "4", "7"))
    x_mid = _avg(xs("2", "5", "8"))
    x_right = _avg(xs("3", "6", "9"))
    if x_right is None and "3" in by_digit:
        x_right = by_digit["3"].x
    if x_left is None and "7" in by_digit:
        x_left = by_digit["7"].x
    if x_mid is None and "8" in by_digit:
        x_mid = by_digit["8"].x
    if x_left is not None and x_right is not None and x_mid is None:
        x_mid = (x_left + x_right) / 2
    if x_mid is not None and x_right is not None and x_left is None:
        x_left = 2 * x_mid - x_right
    if x_left is not None and x_mid is not None and x_right is None:
        x_right = 2 * x_mid - x_left

    y_r1 = _avg(ys("1", "2", "3"))
    y_r2 = _avg(ys("4", "5", "6"))
    y_r3 = _avg(ys("7", "8", "9"))

    spacings = []
    if y_r1 is not None and y_r2 is not None:
        spacings.append(y_r2 - y_r1)
    if y_r2 is not None and y_r3 is not None:
        spacings.append(y_r3 - y_r2)
    row_h = _avg(spacings) or 58.0

    if y_r1 is None and y_r2 is not None and y_r3 is not None:
        y_r1 = y_r2 - row_h
    if y_r2 is None and y_r1 is not None and y_r3 is not None:
        y_r2 = (y_r1 + y_r3) / 2
    if y_r3 is None and y_r2 is not None:
        y_r3 = y_r2 + row_h
    if y_r2 is None and y_r1 is not None and y_r3 is None and "6" in by_digit:
        y_r2 = by_digit["6"].y
    if y_r1 is None and y_r2 is not None and "3" in by_digit:
        y_r1 = by_digit["3"].y

    col_x = {0: x_left, 1: x_mid, 2: x_right}
    row_y = {0: y_r1, 1: y_r2, 2: y_r3}
    grid_pos = {
        "1": (0, 0), "2": (1, 0), "3": (2, 0),
        "4": (0, 1), "5": (1, 1), "6": (2, 1),
        "7": (0, 2), "8": (1, 2), "9": (2, 2),
    }

    extra: list[OcrHit] = []
    if all(v is not None for v in col_x.values()) and all(v is not None for v in row_y.values()):
        for digit, (col, row) in grid_pos.items():
            if digit in by_digit:
                continue
            cx = col_x[col]
            cy = row_y[row]
            if cx is None or cy is None:
                continue
            extra.append(OcrHit(digit, 1.0, cx, cy, w, h, inferred=True))

    if "0" not in by_digit and x_mid is not None and y_r3 is not None:
        extra.append(OcrHit("0", 1.0, x_mid, y_r3 + row_h, w, h, inferred=True))

    digit_map: dict[str, OcrHit] = dict(by_digit)
    for item in extra:
        digit_map.setdefault(item.text, item)

    keypad = {k: v for k, v in digit_map.items() if k in "123456789"}
    if "0" not in digit_map and keypad:
        anchor = (
            keypad.get("8")
            or keypad.get("5")
            or keypad.get("2")
            or next(iter(keypad.values()))
        )
        row_ys = [keypad[d].y for d in ("7", "8", "9") if d in keypad]
        base_y = _avg(row_ys) if row_ys else max(v.y for v in keypad.values())
        prev_y = _avg([keypad[d].y for d in ("4", "5", "6") if d in keypad])
        step = (base_y - prev_y) if prev_y is not None else row_h
        if step < 40:
            step = row_h if row_h >= 40 else 150.0
        digit_map["0"] = OcrHit(
            "0", 1.0, anchor.x, base_y + step, w, h, inferred=True
        )

    non_digit = [
        hit
        for hit in hits
        if not (len(hit.text.strip()) == 1 and hit.text.strip().isdigit())
    ]
    if not digit_map:
        return hits
    return non_digit + list(digit_map.values())


def vision_bbox_to_pyautogui(
    bbox: tuple[float, float, float, float],
    *,
    image_width: int,
    image_height: int,
    region_left: int = 0,
    region_top: int = 0,
    retina_scale: float = 1.0,
) -> tuple[float, float, float, float]:
    """
    Apple Vision (ocrmac): нормализованный bbox, origin — левый **низ**.
    Экран телефона (adb): пиксели, origin — левый **верх**.
    """
    x, y, w, h = bbox

    px_left = x * image_width
    px_top = (1.0 - y - h) * image_height
    px_width = w * image_width
    px_height = h * image_height

    cx = px_left + px_width / 2
    cy = px_top + px_height / 2

    screen_x = region_left + cx / retina_scale
    screen_y = region_top + cy / retina_scale
    return screen_x, screen_y, px_width / retina_scale, px_height / retina_scale


def run_ocr(
    image: Image.Image,
    *,
    region: tuple[int, int, int, int] | None = None,
    languages: list[str] | None = None,
    confidence_min: float | None = None,
) -> list[OcrHit]:
    """
    Базовый пример ocrmac:

        from ocrmac import ocrmac
        ocrmac.OCR(pil_image, language_preference=["ru-RU"]).recognize()
        # → [(text, confidence, (x, y, w, h)), ...]
    """
    from ocrmac import ocrmac

    cfg = ocr_settings()
    lang = languages or cfg.get("languages") or ["ru-RU", "en-US"]
    min_conf = (
        float(confidence_min)
        if confidence_min is not None
        else float(cfg.get("confidence_min", 0.35))
    )

    raw = ocrmac.OCR(image, language_preference=lang).recognize()

    img_w, img_h = image.size
    left, top = region_offset(region)
    capture = region if region is not None else capture_region()
    scale = get_retina_scale(image, region=capture)

    hits: list[OcrHit] = []
    for text, confidence, bbox in raw:
        if confidence < min_conf:
            continue
        sx, sy, sw, sh = vision_bbox_to_pyautogui(
            bbox,
            image_width=img_w,
            image_height=img_h,
            region_left=left,
            region_top=top,
            retina_scale=scale,
        )
        cleaned = text.strip()
        if not cleaned:
            continue
        hits.append(
            OcrHit(
                text=cleaned,
                confidence=float(confidence),
                x=sx,
                y=sy,
                width=sw,
                height=sh,
                inferred=False,
            )
        )
    return enrich_keypad_digits(hits)


def find_digit(hits: list[OcrHit], digit: str) -> OcrHit | None:
    """Точное совпадение одной цифры на PIN-клавиатуре."""
    hit = find_text(hits, digit, partial=False)
    if hit is not None:
        return hit
    if digit == "0":
        return find_text(hits, "O", partial=False) or find_text(hits, "o", partial=False)
    return None


def find_text(
    hits: list[OcrHit],
    target: str,
    *,
    partial: bool = True,
) -> OcrHit | None:
    needle = target.strip().lower()
    for hit in hits:
        hay = hit.text.lower()
        if partial and needle in hay:
            return hit
        if not partial and hay == needle:
            return hit
    return None


def find_any_text(
    hits: list[OcrHit],
    targets: list[str],
    *,
    partial: bool = True,
) -> OcrHit | None:
    for target in targets:
        hit = find_text(hits, target, partial=partial)
        if hit is not None:
            return hit
    return None
