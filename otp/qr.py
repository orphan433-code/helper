"""Чтение QR с картинки → текст (otpauth-migration URI)."""

from __future__ import annotations

from pathlib import Path


def read_qr_texts(image_path: str | Path) -> list[str]:
    """
    Декод всех QR на изображении.

    Нужен пакет zxing-cpp (+ Pillow уже в проекте).
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"нет файла: {path}")

    try:
        import zxingcpp
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "для --image нужен zxing-cpp: pip install zxing-cpp"
        ) from exc

    img = Image.open(path)
    results = zxingcpp.read_barcodes(img)
    texts = [r.text.strip() for r in results if r.text and r.text.strip()]
    if not texts:
        raise ValueError(f"QR не найден на изображении: {path}")
    return texts
