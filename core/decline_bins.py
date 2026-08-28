"""BIN отмены: каталог банков в коде, едет через git pull. config.yaml не нужен."""

from core.bank_bins import all_catalog_bins, bins_for

DECLINE_BIN_PREFIXES: tuple[str, ...] = all_catalog_bins()
DECLINE_DEFAULT_ON: frozenset[str] = frozenset(
    (
        *bins_for("tbc"),
        *bins_for("bog", visa=False, mastercard=True),
    )
)
DECLINE_DEFAULT_PER_RUN = 10
DECLINE_MAX_PER_RUN = 2000


def clamp_decline_limit(raw: object) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DECLINE_DEFAULT_PER_RUN
    if n <= 0:
        return 0
    return max(1, min(DECLINE_MAX_PER_RUN, n))
