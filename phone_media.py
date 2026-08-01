"""Автодетект папок скринов/видео на Android через adb.

При check_adb сканируем типичные пути + (опционально) MediaStore,
чтобы понять, откуда потом тянуть чеки и ролики.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from adb_device import pick_serial, run_adb

# Кандидаты: сначала короткие /sdcard/…, потом /storage/emulated/0/…
_SCREEN_CANDIDATES = (
    "/sdcard/DCIM/Screenshots",
    "/sdcard/Pictures/Screenshots",
    "/storage/emulated/0/DCIM/Screenshots",
    "/storage/emulated/0/Pictures/Screenshots",
)
_VIDEO_CANDIDATES = (
    "/sdcard/Movies/ScreenRecord",
    "/sdcard/DCIM/Screen recordings",
    "/sdcard/Movies",
    "/sdcard/DCIM/Camera",
    "/sdcard/Pictures/Screenshots",
    "/storage/emulated/0/Movies/ScreenRecord",
    "/storage/emulated/0/DCIM/Screen recordings",
    "/storage/emulated/0/Movies",
    "/storage/emulated/0/DCIM/Camera",
)

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".heic")
_VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".3gp")

_cached: PhoneMediaDirs | None = None


@dataclass
class PhoneMediaDirs:
    screens_dir: str = ""
    videos_dir: str = ""
    screens_candidates: list[str] = field(default_factory=list)
    videos_candidates: list[str] = field(default_factory=list)
    screens_sample: str = ""
    videos_sample: str = ""
    mediastore_image: str = ""
    mediastore_video: str = ""
    ok: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.screens_dir:
            lines.append(f"Скрины: {self.screens_dir}")
            if self.screens_sample:
                lines.append(f"  последний: {self.screens_sample}")
        else:
            lines.append("Скрины: папка не найдена")
        if self.videos_dir:
            lines.append(f"Видео:  {self.videos_dir}")
            if self.videos_sample:
                lines.append(f"  последний: {self.videos_sample}")
        else:
            lines.append("Видео:  папка не найдена")
        if self.mediastore_image:
            lines.append(f"MediaStore image: {self.mediastore_image}")
        if self.mediastore_video:
            lines.append(f"MediaStore video: {self.mediastore_video}")
        return lines


def get_cached_media_dirs() -> PhoneMediaDirs | None:
    return _cached


def _shell(cmd: str, *, serial: str | None = None) -> str:
    proc = run_adb(["shell", cmd], serial=serial if serial else ..., check=False)
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def _dir_exists(path: str, *, serial: str | None = None) -> bool:
    # test -d надёжнее ls на пустых/permission
    out = _shell(f'[ -d "{path}" ] && echo YES || echo NO', serial=serial)
    return "YES" in out


def _list_recent_files(
    path: str,
    *,
    serial: str | None = None,
    limit: int = 8,
) -> list[tuple[int, str]]:
    """[(mtime_epoch, full_path), ...] свежие сверху."""
    # toybox/busybox: ls -1e не везде; берём stat через find -printf если есть,
    # иначе простой ls и без mtime.
    out = _shell(
        f'find "{path}" -maxdepth 1 -type f -printf "%T@ %p\\n" 2>/dev/null | sort -nr | head -n {int(limit)}',
        serial=serial,
    )
    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or " " not in line:
            continue
        ts_s, _, rest = line.partition(" ")
        try:
            ts = int(float(ts_s))
        except ValueError:
            continue
        rows.append((ts, rest.strip()))
    if rows:
        return rows

    # fallback: ls -t
    out2 = _shell(f'ls -1t "{path}" 2>/dev/null | head -n {int(limit)}', serial=serial)
    now = int(time.time())
    for name in out2.splitlines():
        name = name.strip()
        if not name or name in (".", ".."):
            continue
        rows.append((now, f"{path.rstrip('/')}/{name}"))
    return rows


def _pick_dir_with_ext(
    candidates: tuple[str, ...],
    exts: tuple[str, ...],
    *,
    serial: str | None = None,
) -> tuple[str, str, list[str]]:
    """Вернуть (best_dir, sample_name, existing_dirs)."""
    existing: list[str] = []
    best = ""
    sample = ""
    best_mtime = -1
    for path in candidates:
        if not _dir_exists(path, serial=serial):
            continue
        # дедуп /sdcard vs /storage/emulated/0
        norm = path.replace("/storage/emulated/0", "/sdcard")
        if any(e.replace("/storage/emulated/0", "/sdcard") == norm for e in existing):
            continue
        existing.append(path)
        for mtime, full in _list_recent_files(path, serial=serial, limit=12):
            low = full.lower()
            if not any(low.endswith(ext) for ext in exts):
                continue
            if mtime >= best_mtime:
                best_mtime = mtime
                best = path
                sample = full.rsplit("/", 1)[-1]
                break
        if not best and not sample:
            # папка есть, файлов нужного типа пока нет — всё равно кандидат
            if not best:
                best = path
    if not best and existing:
        best = existing[0]
    return best, sample, existing


_DATA_RE = re.compile(r"(?:_data=|DATA=)([^\s,]+)")


def _mediastore_latest(
    *,
    kind: str,
    serial: str | None = None,
) -> str:
    """kind: images|video → путь последнего файла или ''."""
    if kind == "video":
        uri = "content://media/external/video/media"
    else:
        uri = "content://media/external/images/media"
    # --sort поддерживается не везде; берём пачку и выбираем max date на стороне Python
    out = _shell(
        "content query --uri "
        f"{uri} "
        '--projection "_data:date_added" '
        '--sort "date_added DESC" 2>/dev/null | head -n 5',
        serial=serial,
    )
    for line in out.splitlines():
        m = _DATA_RE.search(line)
        if m:
            path = m.group(1).strip()
            if path and path != "null":
                return path
    return ""


def _parent_dir(path: str) -> str:
    if not path or "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def detect_phone_media_dirs(
    *,
    serial: str | None = None,
    use_mediastore: bool = True,
) -> PhoneMediaDirs:
    """Сканировать устройство. Результат кэшируется."""
    global _cached
    result = PhoneMediaDirs()
    try:
        resolved = serial if serial is not None else pick_serial()
        if not resolved:
            # всё равно пробуем без -s, если одно устройство
            resolved = None

        screens, screen_sample, screen_cands = _pick_dir_with_ext(
            _SCREEN_CANDIDATES, _IMAGE_EXT, serial=resolved
        )
        videos, video_sample, video_cands = _pick_dir_with_ext(
            _VIDEO_CANDIDATES, _VIDEO_EXT, serial=resolved
        )

        ms_image = ""
        ms_video = ""
        if use_mediastore:
            try:
                ms_image = _mediastore_latest(kind="images", serial=resolved)
            except Exception:
                ms_image = ""
            try:
                ms_video = _mediastore_latest(kind="video", serial=resolved)
            except Exception:
                ms_video = ""

        # Если папку не нашли, но MediaStore знает файл — возьмём родителя.
        # Также: если папка есть, но без sample, а MediaStore дал файл — предпочитаем его.
        if ms_image:
            ms_screens = _parent_dir(ms_image)
            if not screens or not screen_sample:
                screens = ms_screens or screens
                screen_sample = ms_image.rsplit("/", 1)[-1]
                if ms_screens and ms_screens not in screen_cands:
                    screen_cands.append(ms_screens)
        if ms_video:
            ms_videos = _parent_dir(ms_video)
            if not videos or not video_sample:
                videos = ms_videos or videos
                video_sample = ms_video.rsplit("/", 1)[-1]
                if ms_videos and ms_videos not in video_cands:
                    video_cands.append(ms_videos)

        result.screens_dir = screens
        result.videos_dir = videos
        result.screens_candidates = screen_cands
        result.videos_candidates = video_cands
        result.screens_sample = screen_sample
        result.videos_sample = video_sample
        result.mediastore_image = ms_image
        result.mediastore_video = ms_video
        result.ok = bool(screens or videos or ms_image or ms_video)
    except Exception as exc:
        result.error = str(exc)
        result.ok = False

    _cached = result
    return result


def local_pull_dir(kind: str) -> Path:
    """kind: screens|videos — тянем в proofs_dir / videos_dir (без .runtime)."""
    from completion_registry import proofs_dir, videos_dir

    path = proofs_dir() if kind == "screens" else videos_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_media_dirs(*, serial: str | None = None) -> PhoneMediaDirs:
    cached = get_cached_media_dirs()
    if cached is not None and cached.ok:
        return cached
    return detect_phone_media_dirs(serial=serial)


def _pull_remote_file(
    remote_path: str,
    local_path: Path,
    *,
    serial: str | None = None,
) -> bool:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    proc = run_adb(
        ["pull", remote_path, str(local_path)],
        serial=serial if serial is not None else ...,
        check=False,
    )
    return proc.returncode == 0 and local_path.is_file()


def pull_new_phone_media(
    *,
    kind: str,
    since_ts: float = 0.0,
    serial: str | None = None,
) -> list[Path]:
    """
    Стянуть с телефона новые скрины/видео в proofs_dir / videos_dir.
    kind: screens|videos
    since_ts: unix mtime (сек), 0 = все свежие в папке.
    """
    dirs = ensure_media_dirs(serial=serial)
    remote = dirs.screens_dir if kind == "screens" else dirs.videos_dir
    exts = _IMAGE_EXT if kind == "screens" else _VIDEO_EXT
    if not remote:
        return []

    local_dir = local_pull_dir(kind)
    resolved = serial if serial is not None else pick_serial()
    pulled: list[Path] = []

    for mtime, full in _list_recent_files(remote, serial=resolved, limit=40):
        low = full.lower()
        if not any(low.endswith(ext) for ext in exts):
            continue
        if since_ts and mtime < since_ts - 2:
            # небольшой запас на рассинхрон часов телефона/мака
            continue
        name = full.rsplit("/", 1)[-1]
        if not name or name.startswith("."):
            continue
        dest = local_dir / name
        if dest.is_file():
            # уже тянули — не перезаписываем, отдаём как кандидат
            pulled.append(dest)
            continue
        if _pull_remote_file(full, dest, serial=resolved):
            pulled.append(dest)

    return sorted(pulled, key=lambda p: p.stat().st_mtime)
