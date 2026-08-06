#!/bin/bash
# Собрать TJSBOT.app для Apple Silicon (arm64), без Rosetta
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
TZK="$PROJECT"
APP="$PROJECT/TJSBOT.app"
PY="$PROJECT/.venv/bin/python3"
LAUNCHER_SRC="$TZK/macos/launcher_main.py"
MACOS="$APP/Contents/MacOS"

if [[ ! -x "$PY" ]]; then
  echo "Нет Python: $PY" >&2
  exit 1
fi

HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" != "arm64" ]]; then
  echo "[WARN] Сборка на $HOST_ARCH — на M1/M2/M3 лучше запускать на самом Mac" >&2
fi

rm -rf "$APP"
mkdir -p "$MACOS"

cp "$TZK/macos/TJSBOT.Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' >"$APP/Contents/PkgInfo"
cp "$LAUNCHER_SRC" "$MACOS/launcher_main.py"

# Явно arm64 — pywebview + WKWebView на M1
cat >"$MACOS/tjsbot-gui" <<'EOF'
#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$(cd "$ROOT/../.." && pwd)"
PROJECT="$(dirname "$APP")"
PY="$PROJECT/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  osascript -e 'display alert "TJSBOT" message "Не найден .venv/bin/python3" as critical'
  exit 1
fi
cd "$ROOT"
exec /usr/bin/arch -arm64 "$PY" "$ROOT/launcher_main.py"
EOF

chmod +x "$MACOS/tjsbot-gui"
xattr -cr "$APP" 2>/dev/null || true
xattr -cr "$PROJECT" 2>/dev/null || true

ENT="$TZK/macos/TJSBOT.entitlements"
if [[ -f "$ENT" ]] && command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - --entitlements "$ENT" "$APP" 2>/dev/null || true
fi

echo "OK: $APP (arm64)"
echo "Android: USB debugging + adb devices"
echo "Архитектура: $(file "$PY" | sed 's/.*executable/arm64+python/')"
echo "Запуск: двойной клик по TJSBOT.app"
