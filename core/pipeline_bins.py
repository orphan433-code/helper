"""BIN пайплайна «Уходят». Вкл — берём только эти (бренд Visa/MC не режет)."""

from core.bank_bins import normalize_known_prefixes

PIPELINE_BIN_PREFIXES: tuple[str, ...] = (
    "4098",
    "410170",
    "537524",
    "557755",
)


def normalize_pipeline_bin_prefixes(raw: object) -> list[str]:
    return normalize_known_prefixes(raw, PIPELINE_BIN_PREFIXES)
