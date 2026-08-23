#!/bin/bash
# Экспорт team-настроек. --with-secrets = PIN + API для личной передачи.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m core.config_bundle export "$@"
