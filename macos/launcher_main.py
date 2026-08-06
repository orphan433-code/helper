"""Точка входа для TJSBOT.app (пути относительно bundle или repo)."""

from __future__ import annotations

import os
import sys


def _bootstrap() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # repo: .../TJSBOT/macos/launcher_main.py
    parent = os.path.dirname(here)
    if os.path.basename(here) == "macos" and os.path.isfile(
        os.path.join(parent, "start.sh")
    ):
        root = parent
    else:
        # bundle: TJSBOT.app/Contents/MacOS/launcher_main.py
        contents = os.path.dirname(here)
        app_bundle = os.path.dirname(contents)
        project = os.path.dirname(app_bundle)
        nested = os.path.join(project, "TJSBOT")
        root = nested if os.path.isdir(nested) else project
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> None:
    _bootstrap()
    from ui.web import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
