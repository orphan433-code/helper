#!/usr/bin/env python3
"""tzk — консольный запуск. GUI: python app_gui.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_runner import main

if __name__ == "__main__":
    sys.exit(main())
