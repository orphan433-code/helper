"""BIN основного пайплайна (Accept→банк) — список в коде."""

from core.redirect_bins import (
    REDIRECT_BIN_PREFIXES as PIPELINE_BIN_PREFIXES,
    normalize_redirect_prefixes as normalize_pipeline_bin_prefixes,
)

__all__ = ["PIPELINE_BIN_PREFIXES", "normalize_pipeline_bin_prefixes"]
