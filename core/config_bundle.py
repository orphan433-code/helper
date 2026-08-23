"""Перенос настроек команды: export → zip → import у коллеги.

По умолчанию секреты (PIN, API-ключи, token) маскируются.
`include_secrets=True` — полный bundle для личной передачи.
При import реальные секреты из bundle применяются; placeholder не затирает локальные.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.paths import ROOT

BUNDLE_VERSION = 1
BUNDLE_EXT = ".tjsbundle.zip"

# Файлы, которые едут в bundle (относительно ROOT)
BUNDLE_FILES: tuple[str, ...] = (
    "config.yaml",
    "platcore-decline/config.yaml",
    "runtime/deals_ui.yaml",
)

REDACTED = "__FILL_LOCALLY__"

# Ключи/пути, которые не выгружаем в открытую
_SECRET_KEY_RE = re.compile(
    r"(^pin$|password|secret|token|api_key|gemini_api_key)",
    re.IGNORECASE,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(str(key)))


def _collect_redacted_paths(node: Any, *, found: list[str], path: str = "") -> None:
    if isinstance(node, dict):
        for key, val in node.items():
            key_path = f"{path}.{key}" if path else str(key)
            if _is_secret_key(str(key)) and val in (None, "", REDACTED):
                found.append(key_path)
            else:
                _collect_redacted_paths(val, found=found, path=key_path)
    elif isinstance(node, list):
        for item in node:
            _collect_redacted_paths(item, found=found, path=path)


def _redact_secrets(node: Any, *, found: list[str], path: str = "") -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, val in node.items():
            key_path = f"{path}.{key}" if path else str(key)
            if _is_secret_key(str(key)) and val not in (None, "", REDACTED):
                out[key] = REDACTED
                found.append(key_path)
            else:
                out[key] = _redact_secrets(val, found=found, path=key_path)
        return out
    if isinstance(node, list):
        return [_redact_secrets(x, found=found, path=path) for x in node]
    return node


def _deep_merge(
    incoming: dict[str, Any],
    local: dict[str, Any],
    *,
    preserve_local_secrets: bool = True,
) -> dict[str, Any]:
    """incoming поверх local; секреты из local сохраняем если заполнены."""

    def merge(a: Any, b: Any, key: str = "") -> Any:
        if isinstance(a, dict) and isinstance(b, dict):
            out = deepcopy(b)
            for k, v in a.items():
                if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                    out[k] = merge(v, out[k], key=k)
                elif preserve_local_secrets and _is_secret_key(k):
                    if v not in (None, "", REDACTED):
                        out[k] = deepcopy(v)
                    elif out.get(k) not in (None, "", REDACTED):
                        continue
                    else:
                        out[k] = REDACTED if v == REDACTED else deepcopy(v)
                elif v == REDACTED and out.get(k) not in (None, "", REDACTED):
                    continue
                else:
                    out[k] = merge(v, out.get(k), key=k) if isinstance(v, dict) else deepcopy(v)
            return out
        if preserve_local_secrets and _is_secret_key(key) and b not in (None, "", REDACTED):
            return b
        if a == REDACTED and b not in (None, "", REDACTED):
            return b
        return deepcopy(a)

    return merge(incoming, local)


def _default_export_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return ROOT / f"tjs-settings-{stamp}{BUNDLE_EXT}"


def export_bundle(
    out_path: Path | None = None,
    *,
    include_secrets: bool = False,
) -> Path:
    out = Path(out_path or _default_export_path()).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    redacted_paths: list[str] = []
    manifest_files: list[str] = []

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in BUNDLE_FILES:
            src = ROOT / rel
            if not src.is_file():
                continue
            raw = _load_yaml(src)
            if include_secrets:
                payload = raw
            else:
                found: list[str] = []
                payload = _redact_secrets(raw, found=found)
                redacted_paths.extend(found)
            zf.writestr(f"files/{rel}", _dump_yaml(payload))
            manifest_files.append(rel)

        notes = [
            "Сессия PlatCore (browser_profile) в bundle не входит — логин отдельно.",
        ]
        if include_secrets:
            notes.append(
                "Bundle содержит PIN и API-ключи — передавай только доверенным коллегам."
            )
        else:
            notes.append(f"Секреты помечены как {REDACTED} — каждый заполняет у себя.")

        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root_label": ROOT.name,
            "files": manifest_files,
            "includes_secrets": include_secrets,
            "secrets_redacted": [] if include_secrets else sorted(set(redacted_paths)),
            "notes": notes,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return out


def import_bundle(
    bundle_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    bundle_path = bundle_path.expanduser().resolve()
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Bundle не найден: {bundle_path}")

    report: dict[str, Any] = {
        "imported": [],
        "skipped_missing_in_bundle": [],
        "backups": [],
        "fill_locally": [],
        "dry_run": dry_run,
    }

    with zipfile.ZipFile(bundle_path, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("Некорректный bundle: нет manifest.json") from exc

        if int(manifest.get("bundle_version") or 0) != BUNDLE_VERSION:
            raise ValueError(
                f"Версия bundle {manifest.get('bundle_version')} "
                f"≠ поддерживаемая {BUNDLE_VERSION}"
            )

        report["includes_secrets"] = bool(manifest.get("includes_secrets"))
        names = {n for n in zf.namelist() if n.startswith("files/")}
        still_missing: list[str] = []

        for rel in BUNDLE_FILES:
            entry = f"files/{rel}"
            if entry not in names:
                report["skipped_missing_in_bundle"].append(rel)
                continue

            incoming = yaml.safe_load(zf.read(entry).decode("utf-8")) or {}
            if not isinstance(incoming, dict):
                raise ValueError(f"Файл в bundle не dict: {rel}")

            dst = ROOT / rel
            local = _load_yaml(dst) if dst.is_file() else {}
            merged = _deep_merge(incoming, local)
            found: list[str] = []
            _collect_redacted_paths(merged, found=found)
            still_missing.extend(found)

            if dry_run:
                report["imported"].append({"path": rel, "action": "would_write"})
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_file():
                backup_dir = ROOT / "runtime" / "config_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = backup_dir / f"{rel.replace('/', '__')}.{stamp}.bak"
                shutil.copy2(dst, backup)
                report["backups"].append(str(backup.relative_to(ROOT)))

            with dst.open("w", encoding="utf-8") as fh:
                fh.write(_dump_yaml(merged))
            report["imported"].append({"path": rel, "action": "written"})

        report["fill_locally"] = sorted(set(still_missing))

    return report


def _print_report(report: dict[str, Any]) -> None:
    mode = "DRY-RUN" if report.get("dry_run") else "IMPORT"
    print(f"\n=== TJS config bundle ({mode}) ===\n")
    for item in report.get("imported") or []:
        print(f"  ✓ {item['path']} — {item['action']}")
    for rel in report.get("skipped_missing_in_bundle") or []:
        print(f"  · {rel} — нет в bundle, пропуск")
    for bak in report.get("backups") or []:
        print(f"  ↩ backup: {bak}")
    fill = report.get("fill_locally") or []
    if fill:
        print("\nЗаполни локально (не передавать коллегам):")
        for path in fill:
            print(f"  - {path}")
    print("\nОтдельно у каждого:")
    print("  - bank.pin в config.yaml")
    print("  - agent.gemini_api_key (если нужен AI)")
    print("  - browser_profile / логин PlatCore")
    print("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Экспорт/импорт team-настроек TJS"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    exp = sub.add_parser("export", help="Собрать bundle для коллег")
    exp.add_argument(
        "-o",
        "--output",
        help=f"Путь к zip (по умолчанию tjs-settings-YYYYMMDD-HHMM{BUNDLE_EXT})",
    )
    exp.add_argument(
        "--with-secrets",
        action="store_true",
        help="Включить PIN, Gemini-ключ и token (личная передача)",
    )

    imp = sub.add_parser("import", help="Применить bundle у коллеги")
    imp.add_argument("bundle", help="Путь к .tjsbundle.zip")
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать что изменится",
    )

    args = parser.parse_args(argv)

    try:
        if args.cmd == "export":
            out = export_bundle(
                Path(args.output) if args.output else None,
                include_secrets=bool(args.with_secrets),
            )
            print(f"\n✓ Bundle создан:\n  {out}\n")
            if args.with_secrets:
                print("⚠ В bundle есть PIN и API-ключи — только личная передача.")
            print("Передай коллегам файл + bash setup.sh (если ещё не ставили).")
            print(f"Импорт: python -m core.config_bundle import \"{out.name}\"\n")
            return 0

        report = import_bundle(Path(args.bundle), dry_run=bool(args.dry_run))
        _print_report(report)
        return 0
    except Exception as exc:
        print(f"\n✗ {exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
