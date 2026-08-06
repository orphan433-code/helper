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

# Build frontend if missing (browser UI)
if [[ ! -f web_ui/dist/index.html ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Собираю web UI…"
    (cd web_ui && npm install && npm run build)
  else
    echo "Нет npm и нет web_ui/dist — поставь Node.js или собери UI заранее." >&2
    exit 1
  fi
fi

cleanup() {
  # Страховка: python уже сделал hard stop, но Chromium иногда выживает
  if [[ -x .venv/bin/python ]]; then
    .venv/bin/python -c 'from core.hard_stop import kill_browser_profiles, wipe_children_of_self; kill_browser_profiles(); wipe_children_of_self()' 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "TJSBOT → $URL"
echo "Остановка: Ctrl+C (полное убийство процессов)"
# Не exec: EXIT-trap подчистит хвосты после python
.venv/bin/python -m ui.browser || true

echo
echo "Сервер остановлен."
# Держим терминал открытым — иначе некоторые IDE закрывают вкладку сразу
# после выхода процесса (Cursor/VSCode: close-on-exit для терминала).
read -r -p "Нажми Enter, чтобы закрыть окно… " _ANSWER || true
