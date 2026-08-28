"""BIN редиректа: каталог банков + старый extra BIN. Едет через git pull."""

from core.bank_bins import EXTRA_REDIRECT_BINS, all_catalog_bins, normalize_known_prefixes

_catalog = all_catalog_bins()
_extra = tuple(p for p in EXTRA_REDIRECT_BINS if p not in _catalog)
REDIRECT_BIN_PREFIXES: tuple[str, ...] = (*_catalog, *_extra)


def normalize_redirect_prefixes(raw: object) -> list[str]:
    return normalize_known_prefixes(raw, REDIRECT_BIN_PREFIXES)
