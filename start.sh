#!/bin/bash
# Запуск TJSBOT в браузере. Если ещё не ставили — сам вызовет setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

URL="http://127.0.0.1:8765"

xattr -cr "$ROOT" 2>/dev/null || true
chmod +x setup.sh start.sh setup.command start.command 2>/dev/null || true

venv_ok() {
  [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys' >/dev/null 2>&1
}

if ! venv_ok; then
  echo "Окружение ещё не готово — запускаю установку…"
  bash "$ROOT/setup.sh"
fi

if ! venv_ok; then
  echo "После setup нет рабочего .venv/bin/python — установка не завершилась." >&2
  exit 1
fi

(
  for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "$URL" 2>/dev/null; then
      open "$URL"
      exit 0
    fi
    sleep 0.25
  done
  open "$URL" 2>/dev/null || true
) &

echo "TJSBOT → $URL"
echo "Остановка: Ctrl+C"
exec .venv/bin/python app_browser.py
