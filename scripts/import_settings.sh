#!/bin/bash
# Импорт team-настроек от коллеги / тимлида
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ $# -lt 1 ]]; then
  echo "Использование: bash scripts/import_settings.sh путь/к/tjs-settings.tjsbundle.zip" >&2
  exit 1
fi

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Нет .venv — сначала: bash setup.sh" >&2
  exit 1
fi

exec "$PY" -m core.config_bundle import "$@"
