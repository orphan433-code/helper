#!/bin/bash
cd "$(dirname "$0")"
xattr -cr . 2>/dev/null || true
bash start.sh
status=$?
if [[ $status -ne 0 ]]; then
  echo ""
  echo "Ошибка запуска (код $status)."
  read -r -p "Нажми Enter, чтобы закрыть окно…"
fi
exit "$status"
