#!/usr/bin/env python3
"""Вход на PlatCore — консоль. GUI: кнопка «Логин» в Tzk.app"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_runner import run_login


def main() -> int:
    asyncio.run(run_login())
    return 0


if __name__ == "__main__":
    sys.exit(main())
