"""GEL → EUR через XE converter. Скрин виджета — в proofs."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.logkit import info, warn
from core.paths import ROOT

_XE_URL = (
    "https://www.xe.com/currencyconverter/convert/"
    "?Amount={amount}&From=GEL&To=EUR"
)
_EURO_RE = re.compile(
    r"(?:€|eur)\s*(\d{1,6}(?:[.,]\d{1,4})?)",
    re.I,
)
_TO_RE = re.compile(
    r"\bto\b[^\d€]{0,40}(?:€\s*)?(\d{1,6}(?:[.,]\d{1,4})?)",
    re.I,
)
_RATE_RE = re.compile(
    r"1(?:[.,]0+)?\s*gel\s*=\s*(0[.,]\d+)\s*eur",
    re.I,
)
_NUM_RE = re.compile(r"(\d{1,6}(?:[.,]\d{1,8})?)")
_GEL_PER_EUR = (0.22, 0.45)
_RATE_MATCH_ABS = 0.02
_RATE_MATCH_REL = 0.005


def _ensure_browsers_path() -> None:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if cache.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cache)


def _fmt_widget_amount(value: float) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)}"


def xe_rate_parts(rate: float) -> tuple[str, str]:
    """Как на XE: 0.33174013 → ('0.33', '174013')."""
    raw = f"{float(rate):.10f}".rstrip("0").rstrip(".")
    if "." not in raw:
        return raw, ""
    head, frac = raw.split(".", 1)
    if len(frac) <= 2:
        return f"{head}.{frac}", ""
    return f"{head}.{frac[:2]}", frac[2:]


def _utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M")


def money2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def _to_float(raw: str) -> float | None:
    try:
        return float(str(raw).strip().replace(",", "."))
    except ValueError:
        return None


def _gel_fraction_tail(amount_gel: float) -> float | None:
    """84.25 → 25. Хвост суммы GEL нельзя брать как EUR."""
    text = f"{float(amount_gel):.4f}".rstrip("0").rstrip(".")
    if "." not in text:
        return None
    tail = text.split(".", 1)[1]
    if not tail:
        return None
    return _to_float(tail)


def looks_like_gel_eur_rate(value: float) -> bool:
    return _GEL_PER_EUR[0] <= value <= _GEL_PER_EUR[1]


def looks_like_converted_eur(value: float, amount_gel: float) -> bool:
    gel = float(amount_gel)
    if gel <= 0 or value <= 0:
        return False
    if abs(value - gel) < 0.005:
        return False
    tail = _gel_fraction_tail(gel)
    if tail is not None and abs(value - tail) < 0.005:
        return False
    lo = gel * _GEL_PER_EUR[0]
    hi = gel * _GEL_PER_EUR[1]
    return lo <= value <= hi


def eur_from_gel_rate(amount_gel: float, rate: float) -> float:
    return money2(
        float(Decimal(str(amount_gel)) * Decimal(str(rate)))
    )


def _matches_rate_eur(value: float, expected: float) -> bool:
    if expected <= 0 or value <= 0:
        return False
    delta = abs(value - expected)
    return delta <= max(_RATE_MATCH_ABS, abs(expected) * _RATE_MATCH_REL)


def parse_xe_rate(text: str) -> float | None:
    """На странице несколько курсов — берём самый длинный (0.33174013, не 0.33166)."""
    best: float | None = None
    best_digits = -1
    for hit in _RATE_RE.finditer(text or ""):
        raw = hit.group(1).replace(",", ".")
        rate = _to_float(raw)
        if rate is None or not looks_like_gel_eur_rate(rate):
            continue
        frac = raw.split(".")[1] if "." in raw else ""
        if len(frac) > best_digits:
            best_digits = len(frac)
            best = rate
    return best


def _displayed_eur_candidates(text: str, amount_gel: float) -> list[float]:
    gel = float(amount_gel)
    found: list[float] = []
    seen: set[float] = set()
    for pattern in (_TO_RE, _EURO_RE):
        for match in pattern.finditer(text or ""):
            value = _to_float(match.group(1))
            if value is None or not looks_like_converted_eur(value, gel):
                continue
            rounded = money2(value)
            if rounded in seen:
                continue
            seen.add(rounded)
            found.append(rounded)
    return found


def parse_xe_eur(text: str, amount_gel: float) -> float | None:
    """EUR = GEL × (1 GEL = rate). To €XX — ближайшее к этому, не первое в допуске."""
    gel = float(Decimal(str(amount_gel)))
    hay = text or ""
    rate = parse_xe_rate(hay)
    expected = eur_from_gel_rate(gel, rate) if rate is not None else None
    displayed = _displayed_eur_candidates(hay, gel)

    if expected is not None:
        close = [v for v in displayed if _matches_rate_eur(v, expected)]
        if close:
            return min(close, key=lambda v: (abs(v - expected), -len(str(v))))
        return expected

    if len(displayed) == 1:
        return displayed[0]

    unique: list[float] = []
    seen: set[float] = set()
    for raw in _NUM_RE.findall(hay):
        value = _to_float(raw)
        if value is None or not looks_like_converted_eur(value, gel):
            continue
        rounded = money2(value)
        if rounded in seen:
            continue
        seen.add(rounded)
        unique.append(rounded)
    if len(unique) == 1:
        return unique[0]
    return None


def _eur_from_json(payload: object, amount_gel: float) -> float | None:
    if not isinstance(payload, dict):
        return None
    values: list[float] = []
    to = payload.get("to")
    if isinstance(to, list) and to and isinstance(to[0], dict):
        for key in ("mid", "amount", "result"):
            value = _json_num(to[0].get(key))
            if value is not None:
                values.append(value)
    for key in ("result", "mid"):
        value = _json_num(payload.get(key))
        if value is not None:
            values.append(value)

    rate = _best_rate(values)
    if rate is not None:
        expected = eur_from_gel_rate(amount_gel, rate)
        close = [
            money2(v)
            for v in values
            if looks_like_converted_eur(v, amount_gel)
            and _matches_rate_eur(v, expected)
        ]
        if close:
            return min(close, key=lambda v: abs(v - expected))
        return expected

    converted = [
        money2(v)
        for v in values
        if looks_like_converted_eur(v, amount_gel)
    ]
    if len(set(converted)) == 1:
        return converted[0]
    return None


def _json_num(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        return _to_float(raw)
    return None


def _rate_digits(value: float) -> int:
    text = f"{value:.16f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".")[1])


def _best_rate(values: list[float]) -> float | None:
    rates = [v for v in values if looks_like_gel_eur_rate(v)]
    if not rates:
        return None
    return max(rates, key=_rate_digits)


def _url_amount_matches(resp_url: str, amount_gel: float) -> bool:
    parsed = urlparse(resp_url)
    qs = parse_qs(parsed.query)
    raw = (qs.get("amount") or qs.get("Amount") or [""])[0]
    value = _to_float(raw)
    if value is None:
        return False
    return abs(value - float(amount_gel)) < 0.005


async def _widget_haystack(page: object, body: str) -> str:
    """innerText не видит value инпутов To — €55.89 живёт в input."""
    extras: list[str] = []
    try:
        extras = await page.evaluate(  # type: ignore[union-attr]
            """() => {
              const bits = [];
              for (const el of document.querySelectorAll('input, textarea')) {
                const v = (el.value || '').trim();
                if (v) bits.push(v);
              }
              return bits;
            }"""
        )
    except Exception:
        extras = []
    parts = [body or ""]
    for raw in extras or []:
        text = str(raw).strip()
        if not text:
            continue
        parts.append(f"To €{text} EUR")
        parts.append(text)
    return "\n".join(parts)


async def _dismiss_xe_chrome(page: object) -> None:
    for selector in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept')",
        "button:has-text('Agree')",
        "button:has-text('I Accept')",
        "button:has-text('Allow all')",
    ):
        try:
            btn = page.locator(selector).first  # type: ignore[union-attr]
            if await btn.count() and await btn.is_visible(timeout=800):
                await btn.click(timeout=800)
                await page.wait_for_timeout(400)  # type: ignore[union-attr]
                return
        except Exception:
            continue


async def paint_xe_widget(
    page: object,
    *,
    amount_gel: float,
    amount_eur: float,
    rate: float,
    clock_utc: str | None = None,
) -> None:
    """Вписать в карточку те GEL/EUR/курс/UTC, что идут в банк."""
    gel = _fmt_widget_amount(amount_gel)
    eur = _fmt_widget_amount(amount_eur)
    bold, rest = xe_rate_parts(rate)
    clock = clock_utc or _utc_clock()
    await page.evaluate(  # type: ignore[union-attr]
        """([gel, eur, bold, rest, clock]) => {
          const proto = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
          );
          const setVal = (el, v) => {
            if (!el || !proto || !proto.set) return;
            proto.set.call(el, v);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          };
          const inputs = [...document.querySelectorAll('input[inputmode="decimal"]')];
          if (inputs[0]) setVal(inputs[0], gel);
          if (inputs[1]) setVal(inputs[1], eur);
          const rateP = [...document.querySelectorAll('p')].find((p) =>
            /1(?:\\.00)?\\s*GEL/i.test(p.innerText) && /EUR/i.test(p.innerText)
          );
          if (rateP) {
            const mute = rest
              ? `<span class="text-xe-neutral-700">${rest}</span>`
              : '';
            rateP.innerHTML =
              `<span>1.00 GEL = ${bold}${mute} EUR</span>`;
          }
          const timeP = [...document.querySelectorAll('p')].find((p) =>
            /Mid-market rate/i.test(p.innerText)
          );
          if (timeP) {
            timeP.textContent = `Mid-market rate at ${clock} UTC`;
          }
        }""",
        [gel, eur, bold, rest, clock],
    )


async def screenshot_xe_widget(page: object, shot_path: Path) -> None:
    """Кроп карточки конвертера — как снимок с экрана, не вся страница."""
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    card = page.locator(  # type: ignore[union-attr]
        "div.rounded-3xl.bg-white"
    ).filter(has_text="Mid-market rate").first
    try:
        await card.wait_for(state="visible", timeout=8_000)
    except Exception:
        card = page.locator("form").locator(
            "xpath=ancestor::div[contains(@class,'rounded-3xl')]"
        ).first
        await card.wait_for(state="visible", timeout=5_000)
    await card.scroll_into_view_if_needed()
    await page.wait_for_timeout(200)  # type: ignore[union-attr]
    box = await card.bounding_box()
    if not box:
        await page.screenshot(path=str(shot_path), full_page=False)  # type: ignore[union-attr]
        return
    pad = 20.0
    vp = page.viewport_size or {"width": 1280, "height": 900}  # type: ignore[union-attr]
    x = max(0.0, box["x"] - pad)
    y = max(0.0, box["y"] - pad)
    w = min(float(vp["width"]) - x, box["width"] + pad * 2)
    h = min(float(vp["height"]) - y, box["height"] + pad * 2)
    await page.screenshot(  # type: ignore[union-attr]
        path=str(shot_path),
        clip={"x": x, "y": y, "width": max(1.0, w), "height": max(1.0, h)},
    )


async def gel_to_eur(
    amount_gel: float,
    *,
    shot_path: Path | None = None,
) -> float:
    """Открыть XE, снять EUR, опционально скрин. Без HZ."""
    from playwright.async_api import async_playwright

    if amount_gel <= 0:
        raise ValueError("EZE XE: GEL ≤ 0")
    _ensure_browsers_path()
    amount_text = f"{amount_gel:.4f}".rstrip("0").rstrip(".")
    url = _XE_URL.format(amount=amount_text)
    info(f"XE GEL→EUR {amount_gel:g}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                device_scale_factor=2,
            )
            page = await context.new_page()
            eur: float | None = None

            async def _on_response(response: object) -> None:
                nonlocal eur
                try:
                    resp_url = str(getattr(response, "url", "") or "")
                    low = resp_url.lower()
                    if "convert" not in low:
                        return
                    if "gel" not in low:
                        return
                    if "eur" not in low:
                        return
                    if not _url_amount_matches(resp_url, amount_gel):
                        return
                    data = await response.json()  # type: ignore[union-attr]
                except Exception:
                    return
                parsed = _eur_from_json(data, amount_gel)
                if parsed is not None:
                    eur = parsed

            page.on("response", _on_response)
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await _dismiss_xe_chrome(page)
            await page.wait_for_timeout(2500)
            body = ""
            try:
                body = await page.inner_text("body")
            except Exception:
                body = ""
            hay = await _widget_haystack(page, body)
            parsed_text = parse_xe_eur(hay, amount_gel) if hay.strip() else None
            if parsed_text is not None:
                eur = parsed_text
            rate = parse_xe_rate(hay)
            if eur is None or eur <= 0:
                raise ValueError(f"XE не отдал EUR для {amount_gel:g} GEL")
            if rate is None or not looks_like_gel_eur_rate(rate):
                rate = float(Decimal(str(eur)) / Decimal(str(amount_gel)))
            rate_txt = f"{rate:.10f}".rstrip("0").rstrip(".")
            info(f"XE курс 1 GEL = {rate_txt} EUR")
            clock = _utc_clock()
            if shot_path is not None:
                try:
                    await paint_xe_widget(
                        page,
                        amount_gel=amount_gel,
                        amount_eur=eur,
                        rate=rate,
                        clock_utc=clock,
                    )
                    await page.wait_for_timeout(150)
                    await screenshot_xe_widget(page, shot_path)
                except Exception as exc:
                    warn(f"XE скрин: {exc}")
                    try:
                        shot_path.parent.mkdir(parents=True, exist_ok=True)
                        await page.screenshot(path=str(shot_path), full_page=False)
                    except Exception:
                        pass
            info(f"XE {amount_gel:g} GEL = {eur:g} EUR")
            return float(eur)
        finally:
            await browser.close()


def xe_shot_path(order_id: str) -> Path:
    safe = "".join(ch for ch in str(order_id) if ch.isalnum() or ch in "-_")[:40]
    return ROOT / "runtime" / "proofs" / f"xe_{safe or 'deal'}.png"
