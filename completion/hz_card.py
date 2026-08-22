"""PNG курса hz-calc — тот же вид, что кнопка Save / третий файл на approve."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_BG = (21, 22, 27)
_LABEL = (124, 123, 138)
_VALUE = (236, 237, 242)
_LABEL_STRONG = (138, 137, 152)
_VALUE_STRONG = (255, 255, 255)

_W, _H = 1024, 277
_H_EUR = 376
_LEFT_X = 42
_RIGHT_X = 981
_ROW1_TOP = 66
_ROW2_TOP = 165
_ROW3_TOP = 270

# (path, index) — Helvetica Neue совпал с шириной оригинала Save.
_FONT_REG = (
    ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
    ("/Library/Fonts/Arial.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
)
_FONT_BOLD = (
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/Library/Fonts/Arial Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
)


def _load_font(specs: tuple[tuple[str, int], ...], size: int) -> ImageFont.ImageFont:
    for path, index in specs:
        if not Path(path).is_file():
            continue
        try:
            return ImageFont.truetype(path, size=size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def _fmt_amt(raw: str | float) -> str:
    text = str(raw).strip().replace(",", "")
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def _fmt_cur(raw: str) -> str:
    return str(raw or "").strip().upper()


def activ_brand_label(card_digits: str = "", *, brand: str = "") -> str:
    hint = (brand or "").strip().lower()
    if hint in ("mc", "mastercard"):
        return "Activ to MC"
    if hint in ("visa",):
        return "Activ to Visa"
    digits = "".join(ch for ch in str(card_digits) if ch.isdigit())
    if digits.startswith("4"):
        return "Activ to Visa"
    if digits[:1] in ("2", "5"):
        return "Activ to MC"
    return "Activ to Visa"


def _draw_left(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    x: int,
    top: int,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((x - bbox[0], top - bbox[1]), text, font=font, fill=fill)


def _draw_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    right: int,
    top: int,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = right - (bbox[2] - bbox[0]) - bbox[0]
    draw.text((x, top - bbox[1]), text, font=font, fill=fill)


def _usd_line(amount_usd: str | float | None) -> str:
    if amount_usd in (None, "", 0, 0.0):
        return ""
    return f"{_fmt_amt(amount_usd)} USD"


def render_hz_card(
    *,
    give_amt: str | float,
    give_cur: str,
    tjs: str | float,
    brand_label: str = "Activ to Visa",
    amount_usd: str | float | None = None,
) -> Image.Image:
    """USD: 2 строки. EUR: 3 — I give (XE) / Activ / Amount USD. Как Save."""
    cur = _fmt_cur(give_cur)
    activ = f"{_fmt_amt(tjs)} TJS"
    row2_label = brand_label.strip() or "Activ to Visa"
    usd_text = _usd_line(amount_usd)
    three = cur == "EUR" and bool(usd_text)

    if three:
        give_label = "I give (XE amount)"
        give = f"{_fmt_amt(give_amt)} EUR"
        height = _H_EUR
    else:
        give_label = "I give"
        give = f"{_fmt_amt(give_amt)} {cur or 'USD'}"
        height = _H

    img = Image.new("RGB", (_W, height), _BG)
    draw = ImageDraw.Draw(img)
    font_row1 = _load_font(_FONT_REG, 46)
    font_row2 = _load_font(_FONT_BOLD, 48)

    _draw_left(draw, give_label, font=font_row1, fill=_LABEL, x=_LEFT_X, top=_ROW1_TOP)
    _draw_right(draw, give, font=font_row1, fill=_VALUE, right=_RIGHT_X, top=_ROW1_TOP)
    _draw_left(
        draw, row2_label, font=font_row2, fill=_LABEL_STRONG, x=_LEFT_X, top=_ROW2_TOP
    )
    _draw_right(
        draw, activ, font=font_row2, fill=_VALUE_STRONG, right=_RIGHT_X, top=_ROW2_TOP
    )
    if three:
        _draw_left(
            draw, "Amount USD", font=font_row1, fill=_LABEL, x=_LEFT_X, top=_ROW3_TOP
        )
        _draw_right(
            draw, usd_text, font=font_row1, fill=_VALUE, right=_RIGHT_X, top=_ROW3_TOP
        )
    return img


def render_from_ledger(
    record: dict,
    *,
    card_digits: str = "",
    brand: str = "",
) -> Image.Image:
    return render_hz_card(
        give_amt=record.get("give_amt") or "0",
        give_cur=str(record.get("give_cur") or "usd"),
        tjs=record.get("tjs") or "0",
        brand_label=activ_brand_label(card_digits, brand=brand),
        amount_usd=record.get("amount_usd"),
    )


def save_hz_card(path: Path, image: Image.Image) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Сгенерировать PNG курса hz-calc")
    parser.add_argument("--give", default="533.50")
    parser.add_argument("--cur", default="usd")
    parser.add_argument("--tjs", default="4945.55")
    parser.add_argument("--usd", default="", help="Amount USD (евро, третья строка)")
    parser.add_argument("--brand", default="visa")
    parser.add_argument("--ledger", default="", help="JSON файл record ledger")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "runtime" / "hz_card.png"),
    )
    args = parser.parse_args()
    if args.ledger:
        raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        record = raw.get("record") if isinstance(raw, dict) and "record" in raw else raw
        img = render_from_ledger(record, brand=args.brand)
    else:
        img = render_hz_card(
            give_amt=args.give,
            give_cur=args.cur,
            tjs=args.tjs,
            brand_label=activ_brand_label(brand=args.brand),
            amount_usd=args.usd or None,
        )
    out = save_hz_card(Path(args.out), img)
    print(out)
