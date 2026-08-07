"""ADB: скриншоты и низкоуровневые команды (USB / Wi‑Fi)."""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

_cached_size: tuple[int, int] | None = None
_cached_serial: str | None = None
_cached_serial_set = False
_adb_bin_cached: str | None = None

_ADB_CANDIDATES = (
    "/opt/homebrew/bin/adb",
    "/usr/local/bin/adb",
    os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
    "/Users/Shared/Android/sdk/platform-tools/adb",
)


def _bank_cfg() -> dict:
    from core.config import bank_settings

    return bank_settings()


def adb_bin() -> str:
    """Абсолютный путь к adb: GUI/Finder часто без /opt/homebrew в PATH."""
    global _adb_bin_cached
    if _adb_bin_cached:
        return _adb_bin_cached
    found = shutil.which("adb")
    if found:
        _adb_bin_cached = found
        return found
    for candidate in _ADB_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            _adb_bin_cached = candidate
            return candidate
    _adb_bin_cached = "adb"
    return _adb_bin_cached


def invalidate_serial_cache() -> None:
    """Сбросить кэш serial (например, при потере устройства)."""
    global _cached_serial, _cached_serial_set
    _cached_serial = None
    _cached_serial_set = False


def _is_network_serial(serial: str) -> bool:
    """Wi‑Fi / tcpip / wireless debugging (не USB transport)."""
    s = serial.strip()
    if not s:
        return False
    if "_adb-tls" in s or s.endswith("._tcp") or "._tcp." in s:
        return True
    # classic `adb connect 192.168.x.x:5555`
    if ":" in s:
        return True
    return False


def _list_ready_serials() -> list[str]:
    """Serial'ы со статусом `device` (готовы к командам)."""
    proc = subprocess.run(
        [adb_bin(), "devices"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    lines = (proc.stdout or b"").decode(errors="replace").strip().splitlines()
    out: list[str] = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            out.append(parts[0])
    return out


def pick_serial(explicit: str | None = None) -> str | None:
    global _cached_serial, _cached_serial_set
    if explicit:
        return explicit
    env = os.environ.get("ANDROID_SERIAL")
    if env:
        return env
    cfg = _bank_cfg().get("adb_serial")
    if cfg:
        return str(cfg).strip() or None

    # Кэш только успешного serial. None не кэшируем — иначе «через раз»
    # после краткого offline / смены USB↔Wi‑Fi.
    if _cached_serial_set and _cached_serial:
        return _cached_serial

    devices = _list_ready_serials()
    if not devices:
        return None

    usb = [s for s in devices if not _is_network_serial(s)]
    net = [s for s in devices if _is_network_serial(s)]

    result: str | None = None
    if len(usb) == 1:
        result = usb[0]
    elif len(usb) > 1:
        print(
            "[WARN] Несколько USB-устройств — укажи bank.adb_serial",
            file=sys.stderr,
        )
        result = usb[0]
    elif len(net) == 1:
        result = net[0]
    elif len(net) > 1:
        print(
            "[WARN] Несколько Wi‑Fi adb — укажи bank.adb_serial "
            "(IP:port или wireless serial)",
            file=sys.stderr,
        )
        result = net[0]
    else:
        result = devices[0]

    if result:
        _cached_serial = result
        _cached_serial_set = True
    return result


def run_adb(
    args: list[str],
    *,
    serial: str | None | object = ...,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """
    serial:
      ... (default) — pick_serial()
      None — без -s (например adb devices)
      str — конкретное устройство
    """
    cmd = [adb_bin()]
    if serial is ...:
        resolved = pick_serial()
    else:
        resolved = serial
    if resolved:
        cmd.extend(["-s", resolved])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, check=check)


def require_device() -> str | None:
    """Найти готовое устройство; при сбое сбросить кэш и повторить один раз."""
    last_err = ""
    for _ in range(2):
        serial = pick_serial()
        proc = run_adb(["get-state"], serial=serial, check=False)
        if proc.returncode == 0:
            state = (proc.stdout or b"").decode(errors="replace").strip()
            if state == "device":
                return serial
            last_err = state or "unknown"
        else:
            err = (proc.stderr or b"").decode(errors="replace").strip()
            last_err = err or f"exit {proc.returncode}"
        invalidate_serial_cache()
    hint = f" ({last_err})" if last_err else ""
    raise RuntimeError(
        "adb не видит телефон. USB / Wi‑Fi debugging, `adb devices`" + hint
    )


def _parse_wm_size(stdout: str) -> tuple[int, int] | None:
    for line in stdout.splitlines():
        line = line.strip()
        if "Physical size:" in line:
            part = line.split("Physical size:", 1)[1].strip()
        elif "Override size:" in line:
            part = line.split("Override size:", 1)[1].strip()
        else:
            continue
        if "x" in part:
            w, h = part.split("x", 1)
            return int(w), int(h)
    return None


def get_display_size(*, refresh: bool = False) -> tuple[int, int]:
    global _cached_size
    if _cached_size is not None and not refresh:
        return _cached_size

    proc = run_adb(["shell", "wm", "size"], check=False)
    size = _parse_wm_size(proc.stdout.decode(errors="replace"))
    if size is not None:
        _cached_size = size
        return size

    # fallback после screencap
    image = screencap_image(refresh_size=False)
    _cached_size = image.size
    return _cached_size


def screencap_image(*, refresh_size: bool = True) -> Image.Image:
    from PIL import Image

    require_device()
    cmd = [adb_bin()]
    serial = pick_serial()
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["exec-out", "screencap", "-p"])
    proc = subprocess.run(cmd, capture_output=True, check=True)
    image = Image.open(io.BytesIO(proc.stdout))
    image.load()

    global _cached_size
    _cached_size = image.size
    return image


def wake_screen() -> None:
    run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=False)
    run_adb(["shell", "input", "keyevent", "KEYCODE_MENU"], check=False)


def set_clipboard(text: str) -> None:
    """
    UTF-8 в буфер обмена Android.

    На многих прошивках (TECNO и др.) `cmd clipboard` — noop с exit 0.
    Тогда вызывающий код должен падать на type_text_raw.
    """
    if not text:
        return
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    script = (
        f"echo {payload} | base64 -d > /data/local/tmp/atz_clip.txt && "
        'cmd clipboard set-text "$(cat /data/local/tmp/atz_clip.txt)"'
    )
    proc = run_adb(["shell", script], check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"clipboard set-text failed: {proc.stderr.decode(errors='replace')}"
        )
    # TECNO/Android 13: команда есть в PATH, но «No shell command implementation»
    err = (proc.stderr or b"").decode(errors="replace")
    out = (proc.stdout or b"").decode(errors="replace")
    if "No shell command implementation" in err or "No shell command implementation" in out:
        raise RuntimeError("clipboard set-text не поддерживается на этом устройстве")


def _escape_input_text(text: str) -> str:
    """Эдскейп для `adb shell input text` (пробел → %s)."""
    specials = "\\()<>|;&*`~\"'"
    out: list[str] = []
    for ch in text:
        if ch == " ":
            out.append("%s")
        elif ch == "%":
            out.append("\\%")
        elif ch in specials:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def type_text_raw(text: str) -> None:
    """
    Ввод в сфокусированное поле через `adb shell input text`.

    Латиница/пробелы ок. На numeric IME (сумма) часто НЕ работает —
    используй type_digits_raw.
    """
    if not text:
        return
    # Не-ASCII (кириллица и т.п.) — input text обычно молча глотает.
    if any(ord(ch) > 127 for ch in text):
        raise RuntimeError(
            "adb input text не умеет кириллицу на этом устройстве — "
            "передайте ФИО латиницей (например TESTOV IVAN)"
        )
    escaped = _escape_input_text(text)
    run_adb(["shell", "input", "text", escaped], check=True)


_DIGIT_KEYCODES: dict[str, str] = {
    "0": "KEYCODE_0",
    "1": "KEYCODE_1",
    "2": "KEYCODE_2",
    "3": "KEYCODE_3",
    "4": "KEYCODE_4",
    "5": "KEYCODE_5",
    "6": "KEYCODE_6",
    "7": "KEYCODE_7",
    "8": "KEYCODE_8",
    "9": "KEYCODE_9",
    ".": "KEYCODE_PERIOD",
    ",": "KEYCODE_COMMA",
}


def type_digits_raw(text: str, *, gap_sec: float = 0.06) -> None:
    """
    Ввод суммы/цифр через keyevent — работает на numeric Gboard.

    `input text` после смены клавы на цифры часто молча ничего не пишет.
    """
    import time

    if not text:
        return
    for ch in text:
        code = _DIGIT_KEYCODES.get(ch)
        if code is None:
            raise RuntimeError(f"type_digits_raw: неподдерживаемый символ {ch!r}")
        keyevent(code)
        if gap_sec > 0:
            time.sleep(gap_sec)


def keyevent(code: str) -> None:
    run_adb(["shell", "input", "keyevent", code], check=True)


def tap_raw(x: int, y: int) -> None:
    # Явный лог: если после ФИО снова «тап по TJS» без этой строки — это не adb tap,
    # а Enter по пустому полю / фокус на валюте.
    print(f"    [ADB TAP] ({x}, {y})", flush=True)
    run_adb(["shell", "input", "tap", str(x), str(y)], check=True)


def swipe_raw(x1: int, y1: int, x2: int, y2: int, *, duration_ms: int = 300) -> None:
    run_adb(
        [
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        ],
        check=True,
    )
