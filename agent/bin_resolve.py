"""BIN каталог + произвольные префиксы карт из NL (5598, 5488…)."""

from __future__ import annotations

import re

from core.decline_bins import DECLINE_BIN_PREFIXES
from core.redirect_bins import REDIRECT_BIN_PREFIXES

_DIGITS_RE = re.compile(r"\b(\d{4,8})\b")


def digits_only(raw: object) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def split_decline_prefix(raw: object) -> tuple[str | None, str | None]:
    """
    Катalog BIN (6 цифр) или свободный префикс карты (4+ цифр).
    5488 → 548888; 5598 → free prefix 5598.
    """
    d = digits_only(raw)
    if len(d) < 4:
        return None, None
    if d in DECLINE_BIN_PREFIXES:
        return d, None
    for p in DECLINE_BIN_PREFIXES:
        if p.startswith(d):
            return p, None
    return None, d


def normalize_card_prefixes(raw: object) -> list[str]:
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        _bin, free = split_decline_prefix(item)
        for p in (free,):
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def normalize_decline_bins(raw: object) -> list[str]:
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        catalog, free = split_decline_prefix(item)
        if catalog and catalog not in seen:
            seen.add(catalog)
            out.append(catalog)
        elif free and free not in seen:
            # короткая форма без match в каталоге — префикс карты
            pass
    return out


def merge_decline_bins_and_prefixes(
    bins_raw: object,
    prefixes_raw: object,
) -> tuple[list[str], list[str]]:
    """Объединить decline_bins + decline_card_prefixes из JSON Gemini."""
    bins: list[str] = []
    prefixes: list[str] = []
    seen_b: set[str] = set()
    seen_p: set[str] = set()
    combined: list[object] = []
    if isinstance(bins_raw, (list, tuple)):
        combined.extend(bins_raw)
    if isinstance(prefixes_raw, (list, tuple)):
        combined.extend(prefixes_raw)
    if isinstance(bins_raw, str):
        combined.extend(bins_raw.split(","))
    if isinstance(prefixes_raw, str):
        combined.extend(prefixes_raw.split(","))
    for item in combined:
        catalog, free = split_decline_prefix(item)
        if catalog and catalog not in seen_b:
            seen_b.add(catalog)
            bins.append(catalog)
        if free and free not in seen_p:
            seen_p.add(free)
            prefixes.append(free)
    return bins, prefixes


def split_redirect_prefix(raw: object) -> tuple[str | None, str | None]:
    """Катalog redirect BIN или свободный префикс карты."""
    d = digits_only(raw)
    if len(d) < 4:
        return None, None
    if d in REDIRECT_BIN_PREFIXES:
        return d, None
    for p in REDIRECT_BIN_PREFIXES:
        if p.startswith(d):
            return p, None
    return None, d


def merge_redirect_bins_and_prefixes(
    bins_raw: object,
    prefixes_raw: object,
) -> tuple[list[str], list[str]]:
    """redirect_bins + redirect_card_prefixes из JSON или текста."""
    bins: list[str] = []
    prefixes: list[str] = []
    seen_b: set[str] = set()
    seen_p: set[str] = set()
    combined: list[object] = []
    if isinstance(bins_raw, (list, tuple)):
        combined.extend(bins_raw)
    elif isinstance(bins_raw, str):
        combined.extend(bins_raw.split(","))
        for match in _DIGITS_RE.finditer(bins_raw):
            combined.append(match.group(1))
    if isinstance(prefixes_raw, (list, tuple)):
        combined.extend(prefixes_raw)
    elif isinstance(prefixes_raw, str):
        combined.extend(prefixes_raw.split(","))
    for item in combined:
        catalog, free = split_redirect_prefix(item)
        if catalog and catalog not in seen_b:
            seen_b.add(catalog)
            bins.append(catalog)
        if free and free not in seen_p:
            seen_p.add(free)
            prefixes.append(free)
    return bins, prefixes


def extract_prefixes_from_text(text: str) -> tuple[list[str], list[str]]:
    """Вытащить 4–8-значные числа из команды (decline-каталог)."""
    bins: list[str] = []
    prefixes: list[str] = []
    seen_b: set[str] = set()
    seen_p: set[str] = set()
    for match in _DIGITS_RE.finditer(str(text or "")):
        catalog, free = split_decline_prefix(match.group(1))
        if catalog and catalog not in seen_b:
            seen_b.add(catalog)
            bins.append(catalog)
        if free and free not in seen_p:
            seen_p.add(free)
            prefixes.append(free)
    return bins, prefixes


def extract_redirect_prefixes_from_text(text: str) -> tuple[list[str], list[str]]:
    """Цифры из команды для redirect."""
    bins: list[str] = []
    prefixes: list[str] = []
    seen_b: set[str] = set()
    seen_p: set[str] = set()
    for match in _DIGITS_RE.finditer(str(text or "")):
        catalog, free = split_redirect_prefix(match.group(1))
        if catalog and catalog not in seen_b:
            seen_b.add(catalog)
            bins.append(catalog)
        if free and free not in seen_p:
            seen_p.add(free)
            prefixes.append(free)
    return bins, prefixes
