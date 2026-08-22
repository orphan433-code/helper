"""BIN редиректа: список в коде, едет через git pull."""

REDIRECT_BIN_PREFIXES: tuple[str, ...] = (
    "537524",
    "557755",
)


def normalize_redirect_prefixes(raw: object) -> list[str]:
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
    return [p for p in REDIRECT_BIN_PREFIXES if p in wanted]
