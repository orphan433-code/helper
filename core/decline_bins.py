"""BIN отмены: список в коде, едет через git pull. config.yaml не нужен."""

DECLINE_BIN_PREFIXES: tuple[str, ...] = (
    "558328",
    "531125",
    "516746",
    "548888",
)
DECLINE_DEFAULT_PER_RUN = 10
DECLINE_MAX_PER_RUN = 50


def clamp_decline_limit(raw: object) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DECLINE_DEFAULT_PER_RUN
    return max(1, min(DECLINE_MAX_PER_RUN, n))
