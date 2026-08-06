"""Скриншоты Android через adb screencap."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from core.config import ROOT, capture_region, ocr_settings

if TYPE_CHECKING:
    Region = tuple[int, int, int, int] | None


def get_retina_scale(
    image: Image.Image | None = None,
    region: Region = None,
) -> float:
    """adb screencap: координаты 1:1 с пикселями телефона."""
    _ = image, region
    return 1.0


def debug_screenshot_path() -> Path:
    cfg = ocr_settings()
    path = Path(cfg["debug_screen_path"])
    if not path.is_absolute():
        path = ROOT / path
    return path


def _debug_path() -> Path:
    return debug_screenshot_path()


def take_screenshot(region: Region = None) -> Image.Image:
    """
    Захват экрана телефона через adb.

    region — опциональный crop в пикселях (по умолчанию весь экран).
    """
    from device.adb import screencap_image

    cfg = ocr_settings()
    image = screencap_image()
    capture = region if region is not None else capture_region()
    if capture is not None:
        left, top, rw, rh = capture
        if (left, top, rw, rh) != (0, 0, image.width, image.height):
            image = image.crop((left, top, left + rw, top + rh))

    if cfg.get("debug_mode", False):
        out = _debug_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out)

    return image


def region_offset(region: Region = None) -> tuple[int, int]:
    capture = region if region is not None else capture_region()
    if capture is None:
        return 0, 0
    return capture[0], capture[1]
