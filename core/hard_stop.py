"""Жёсткая остановка дочерних процессов (Ctrl+C / shutdown UI).

Цель: после выхода не оставлять Chromium / decline / хвосты pipeline.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from core.paths import ROOT

_wiping = False


def _profile_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        from core.config import load_config

        cfg = load_config()
        raw = (cfg.get("browser") or {}).get("user_data_dir")
        if raw:
            dirs.append((ROOT / str(raw)).resolve())
    except Exception:
        pass
    # fallback из example, если config ещё не читается
    fallback = (ROOT / "../CNY/browser_profile").resolve()
    if fallback not in dirs:
        dirs.append(fallback)
    return dirs


def kill_pid(pid: int, *, grace: float = 0.5) -> None:
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except Exception:
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def kill_process_group(pid: int, *, grace: float = 0.6) -> None:
    """Убить группу процессов (нужен start_new_session у Popen)."""
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        kill_pid(pid, grace=grace)
        return
    deadline = time.time() + grace
    while time.time() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        except Exception:
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def kill_popen(proc: Any, *, grace: float = 0.6) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
    except Exception:
        return
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        kill_process_group(pid, grace=grace)
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=0.3)
    except Exception:
        pass


def _pgrep_f(pattern: str) -> list[int]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", pattern],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    pids: list[int] = []
    me = os.getpid()
    for line in out.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        if pid == me:
            continue
        pids.append(pid)
    return pids


def kill_matching(patterns: list[str]) -> int:
    killed = 0
    seen: set[int] = set()
    for pat in patterns:
        if not pat:
            continue
        for pid in _pgrep_f(pat):
            if pid in seen:
                continue
            seen.add(pid)
            kill_pid(pid)
            killed += 1
    return killed


def kill_browser_profiles() -> int:
    """Убить Chromium/Playwright, держащие наш user-data-dir."""
    patterns: list[str] = []
    for d in _profile_dirs():
        # cmdline Playwright обычно содержит абсолютный путь профиля
        patterns.append(str(d))
    # узкие маркеры нашего проекта (не трогаем обычный Chrome пользователя)
    patterns.extend(
        [
            str((ROOT / "platcore-decline").resolve()),
            "decline_by_bank_api",
        ]
    )
    return kill_matching(patterns)


def wipe_children_of_self() -> int:
    """SIGTERM/SIGKILL прямым детям текущего процесса."""
    me = os.getpid()
    killed = 0
    try:
        out = subprocess.check_output(
            ["pgrep", "-P", str(me)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return 0
    for line in out.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        kill_pid(pid)
        killed += 1
    return killed


def hard_stop_runtime(api: Any | None = None) -> None:
    """Остановить задачу + убить хвосты. Идемпотентно."""
    global _wiping
    if _wiping:
        return
    _wiping = True
    try:
        if api is not None:
            try:
                stop = getattr(api, "stop_job", None)
                if callable(stop):
                    stop()
            except Exception:
                pass
            try:
                kill_popen(getattr(api, "_subprocess", None))
            except Exception:
                pass
        try:
            from notify.cancel import stop_cancel_watch_now

            stop_cancel_watch_now()
        except Exception:
            pass
        kill_browser_profiles()
        wipe_children_of_self()
        # второй проход — chromium иногда переживает первый SIGTERM
        time.sleep(0.15)
        kill_browser_profiles()
        wipe_children_of_self()
    finally:
        _wiping = False


def hard_exit(api: Any | None = None, *, code: int = 0) -> None:
    try:
        print("\nПолная остановка процессов…", flush=True)
    except Exception:
        pass
    try:
        hard_stop_runtime(api)
    except Exception as exc:
        try:
            print(f"hard_stop: {exc}", file=sys.stderr, flush=True)
        except Exception:
            pass
    os._exit(code)
