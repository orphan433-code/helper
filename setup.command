#!/bin/bash
cd "$(dirname "$0")"
xattr -cr . 2>/dev/null || true
chmod +x setup.sh start.sh setup.command start.command 2>/dev/null || true
echo "Идёт установка TJSBOT — может занять 10–20 минут…"
bash setup.sh
echo ""
read -r -p "Нажми Enter, чтобы закрыть окно…"
