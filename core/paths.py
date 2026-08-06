"""Корень репозитория (родитель пакета core/)."""

from __future__ import annotations

from pathlib import Path

# core/paths.py → parents[0]=core, [1]=repo root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT
RUNTIME_DIR = ROOT / "runtime"
