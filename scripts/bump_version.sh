#!/bin/bash
# Обновить VERSION: YYYY.MM.DD или YYYY.MM.DD.N (несколько пушей за день).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="$ROOT/VERSION"
TODAY="$(date +%Y.%m.%d)"

current=""
[[ -f "$FILE" ]] && current="$(tr -d '[:space:]' < "$FILE")"

if [[ -z "$current" || "$current" != "$TODAY" && "$current" != "$TODAY".* ]]; then
  next="$TODAY"
elif [[ "$current" == "$TODAY" ]]; then
  next="${TODAY}.2"
else
  n="${current##*.}"
  if [[ "$n" =~ ^[0-9]+$ ]]; then
    next="${TODAY}.$((n + 1))"
  else
    next="${TODAY}.2"
  fi
fi

printf '%s\n' "$next" > "$FILE"
echo "$next"
