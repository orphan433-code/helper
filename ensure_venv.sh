#!/bin/bash
# Создать/починить .venv и поставить зависимости.
# Вызывается из setup.sh и из кнопки «Обновить».
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

find_python() {
  local cand ver major minor
  for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))' 2>/dev/null || true)"
      [[ -n "$ver" ]] || continue
      major="${ver%%.*}"
      minor="${ver#*.}"
      if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "${minor%%.*}" -ge 10 ]]; }; then
        command -v "$cand"
        return 0
      fi
    fi
  done
  return 1
}

venv_ok() {
  [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys' >/dev/null 2>&1
}

PY="$(find_python || true)"
if [[ -z "$PY" || "$PY" == "/usr/bin/python3" ]]; then
  if command -v brew >/dev/null 2>&1; then
    brew install python >/dev/null 2>&1 || true
    PY="$(find_python || true)"
  fi
fi
[[ -n "$PY" ]] || { echo "Нужен Python 3.10+"; exit 1; }
[[ -f requirements.txt ]] || { echo "Нет requirements.txt"; exit 1; }

if ! venv_ok; then
  if [[ -d .venv ]]; then
    echo "Пересоздаю битый .venv…"
    rm -rf .venv
  else
    echo "Создаю .venv…"
  fi
  "$PY" -m venv .venv
fi

VENV_PY="$ROOT/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null
"$VENV_PY" -m pip install -r requirements.txt
"$VENV_PY" -m playwright install chromium >/dev/null 2>&1 || true
echo "venv OK: $("$VENV_PY" --version 2>&1)"
