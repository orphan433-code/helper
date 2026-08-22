"""Правила редиректа в коде — не в shared config.yaml."""

REDIRECT_MAX_REMAINING_HOURS = 1.0

REDIRECT_SKIP_CARD_PREFIXES: tuple[str, ...] = ("548888",)

REDIRECT_SKIP_BANK_PATTERNS: tuple[str, ...] = (
    "bank of georgia",
    "georgia",
    "bog",
)
