"""Локальные config.yaml из примеров (если ещё нет)."""

from __future__ import annotations

import shutil
from core.paths import ROOT


def ensure_local_configs() -> list[str]:
    """
    Скопировать *.example.yaml → config.yaml, если локального нет.
    Никогда не перезаписывает существующий config.yaml.
    """
    created: list[str] = []
    pairs = (
        (ROOT / "config.example.yaml", ROOT / "config.yaml"),
        (
            ROOT / "platcore-decline" / "config.example.yaml",
            ROOT / "platcore-decline" / "config.yaml",
        ),
    )
    for src, dst in pairs:
        if dst.is_file() or not src.is_file():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        created.append(str(dst.relative_to(ROOT)))
    return created
