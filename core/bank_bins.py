"""Каталог BIN банков: общий для отмены, редиректа и UI."""

from __future__ import annotations

from typing import Any

BANK_BINS: tuple[dict[str, Any], ...] = (
    {
        "id": "bog",
        "name": "Bank of Georgia",
        "visa": ("411634", "414051", "414052", "429594"),
        "mastercard": ("516746", "531125", "548888", "558328"),
    },
    {
        "id": "basis",
        "name": "Basisbank",
        "visa": ("499864",),
        "mastercard": (),
    },
    {
        "id": "liberty",
        "name": "Liberty Bank",
        "visa": ("412570", "412571"),
        "mastercard": ("532434", "537524"),
    },
    {
        "id": "tbc",
        "name": "TBC Bank",
        "visa": ("400881", "412742", "415479", "431570", "431571"),
        "mastercard": ("516185", "518974", "521026", "537493"),
    },
)

# Старый redirect BIN вне справочника банков — оставляем в редиректе.
EXTRA_REDIRECT_BINS: tuple[str, ...] = ("557755",)


def bank_row(bank_id: str) -> dict[str, Any] | None:
    for row in BANK_BINS:
        if row["id"] == bank_id:
            return row
    return None


def bins_for(bank_id: str, *, visa: bool = True, mastercard: bool = True) -> tuple[str, ...]:
    row = bank_row(bank_id)
    if not row:
        return ()
    out: list[str] = []
    if visa:
        out.extend(row["visa"])
    if mastercard:
        out.extend(row["mastercard"])
    return tuple(out)


def all_catalog_bins() -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for row in BANK_BINS:
        for bin_code in (*row["visa"], *row["mastercard"]):
            if bin_code not in seen:
                seen.add(bin_code)
                out.append(bin_code)
    return tuple(out)


def catalog_prompt_line() -> str:
    return ", ".join(all_catalog_bins())


def normalize_known_prefixes(raw: object, catalog: tuple[str, ...]) -> list[str]:
    wanted: set[str] = set()
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    for item in items:
        digits = "".join(ch for ch in str(item) if ch.isdigit())
        if digits:
            wanted.add(digits)
    return [p for p in catalog if p in wanted]
