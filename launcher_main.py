"""Точка входа для TJSBOT.app (пути относительно bundle)."""

from __future__ import annotations

import os
import sys


def _bootstrap() -> None:
    macos = os.path.dirname(os.path.abspath(__file__))
    contents = os.path.dirname(macos)
    app_bundle = os.path.dirname(contents)
    project = os.path.dirname(app_bundle)
    root = os.path.join(project, "TJSBOT")
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _bootstrap()
    from app_web import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
