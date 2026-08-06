"""Обновление TJSBOT с GitHub (git pull или zip с ветки).

Секреты не трогаем: config.yaml, .venv, .runtime, профили браузера.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from core.paths import ROOT
VERSION_FILE = ROOT / "VERSION"
UPDATE_META = ROOT / "update.json"
DEFAULT_REPO_URL = "https://github.com/orphan433-code/helper.git"
ENSURE_VENV = ROOT / "ensure_venv.sh"

# Не перезаписывать при zip-обновлении
_PRESERVE_NAMES = {
    "config.yaml",
    ".env",
    ".venv",
    "venv",
    ".runtime",
    "runtime",
    ".git",
    "browser_profile",
    "pending_deal.json",
    "completion_batch.json",
}
_PRESERVE_SUFFIXES = (".png",)  # debug_*.png локальные


def read_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "?"
    return "?"


def _load_meta() -> dict[str, Any]:
    if not UPDATE_META.is_file():
        return {}
    try:
        data = json.loads(UPDATE_META.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def repo_settings() -> tuple[str, str]:
    """(repo_url, branch) из update.json / env / дефолт helper.git."""
    meta = _load_meta()
    url = (
        os.environ.get("TJSBOT_REPO_URL")
        or str(meta.get("repo_url") or "").strip()
        or DEFAULT_REPO_URL
    )
    branch = (
        os.environ.get("TJSBOT_REPO_BRANCH")
        or str(meta.get("branch") or "main").strip()
        or "main"
    )
    return url, branch


def ensure_venv() -> dict[str, Any]:
    """Создать .venv и поставить requirements (для свежего clone / после update)."""
    script = ENSURE_VENV
    if not script.is_file():
        return {"ok": False, "error": f"Нет {script.name}"}
    try:
        script.chmod(script.stat().st_mode | 0o111)
    except OSError:
        pass
    proc = _run(["/bin/bash", str(script)])
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": out or f"ensure_venv.sh exit {proc.returncode}",
        }
    return {"ok": True, "log": out}

def update_status() -> dict[str, Any]:
    url, branch = repo_settings()
    git_dir = ROOT / ".git"
    return {
        "ok": True,
        "version": read_version(),
        "repo_url": url,
        "branch": branch,
        "has_git": git_dir.is_dir(),
        "configured": bool(url),
    }


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _github_zip_url(repo_url: str, branch: str) -> str:
    """https://github.com/user/repo(.git) → archive zip ветки."""
    raw = repo_url.strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    parsed = urlparse(raw)
    if "github.com" not in (parsed.netloc or ""):
        raise ValueError("Пока поддерживается только GitHub HTTPS URL")
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Непонятный repo URL: {repo_url}")
    owner, name = parts[0], parts[1]
    return f"https://github.com/{owner}/{name}/archive/refs/heads/{branch}.zip"


def _should_preserve(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return True
    if parts[0] in _PRESERVE_NAMES:
        return True
    if parts[0] == "platcore-decline" and len(parts) >= 2 and parts[1] == "config.yaml":
        return True
    name = parts[-1]
    if name.startswith("debug_") and name.endswith(_PRESERVE_SUFFIXES):
        return True
    return False


def _apply_tree(src_root: Path, dest_root: Path) -> list[str]:
    """Скопировать файлы из src в dest, пропуская preserve. Вернуть список изменений."""
    changed: list[str] = []
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src_root)
        if _should_preserve(rel):
            continue
        # служебное из архива
        if rel.parts and rel.parts[0] in (".git",):
            continue
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        changed.append(str(rel))
    return changed


def _update_via_git(branch: str) -> dict[str, Any]:
    before = read_version()
    fetch = _run(["git", "fetch", "origin", branch])
    if fetch.returncode != 0:
        return {
            "ok": False,
            "error": (fetch.stderr or fetch.stdout or "git fetch failed").strip(),
            "version": before,
        }
    pull = _run(["git", "pull", "--ff-only", "origin", branch])
    if pull.returncode != 0:
        return {
            "ok": False,
            "error": (pull.stderr or pull.stdout or "git pull failed").strip(),
            "version": before,
            "hint": "Локальные правки конфликтуют. Сохрани config и сделай чистый clone.",
        }
    after = read_version()
    return {
        "ok": True,
        "method": "git",
        "version_before": before,
        "version": after,
        "changed": before != after,
        "log": (pull.stdout or "").strip(),
        "restart_required": True,
    }


def _update_via_zip(repo_url: str, branch: str) -> dict[str, Any]:
    before = read_version()
    zip_url = _github_zip_url(repo_url, branch)
    with tempfile.TemporaryDirectory(prefix="tjsbot-upd-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "src.zip"
        try:
            with urlopen(zip_url, timeout=120) as resp:  # noqa: S310
                archive.write_bytes(resp.read())
        except Exception as exc:
            return {
                "ok": False,
                "error": f"Не удалось скачать {zip_url}: {exc}",
                "version": before,
            }
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(extract_dir)
        roots = [p for p in extract_dir.iterdir() if p.is_dir()]
        if not roots:
            return {"ok": False, "error": "Пустой архив GitHub", "version": before}
        src = roots[0]
        changed = _apply_tree(src, ROOT)
    after = read_version()
    return {
        "ok": True,
        "method": "zip",
        "version_before": before,
        "version": after,
        "changed": before != after or bool(changed),
        "files_updated": len(changed),
        "restart_required": True,
    }


def apply_update() -> dict[str, Any]:
    """Обновить код, затем доустановить .venv / зависимости."""
    url, branch = repo_settings()
    if not url:
        return {
            "ok": False,
            "error": "Не задан repo_url.",
            "version": read_version(),
        }

    if (ROOT / ".git").is_dir():
        remotes = _run(["git", "remote"])
        if "origin" not in (remotes.stdout or ""):
            _run(["git", "remote", "add", "origin", url])
        result = _update_via_git(branch)
    else:
        result = _update_via_zip(url, branch)

    if not result.get("ok"):
        return result

    venv = ensure_venv()
    result["venv_ok"] = bool(venv.get("ok"))
    if venv.get("ok"):
        result["venv_log"] = venv.get("log") or ""
    else:
        result["venv_error"] = venv.get("error") or "ensure_venv failed"
        # код уже обновлён — не валим всё, но предупреждаем
        result["hint"] = (
            "Код скачан, но .venv не собрался. Запусти: bash ensure_venv.sh "
            "или bash setup.sh"
        )
    return result
