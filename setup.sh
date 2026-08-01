#!/bin/bash
# TJSBOT — полная установка на чистый Mac
# Запуск:  cd ~/Desktop/TJSBOT && bash setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── утилиты ──────────────────────────────────────────────
say()  { printf '\n▸ %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
fail() { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# Карантин zip + права на скрипты
xattr -cr "$ROOT" 2>/dev/null || true
chmod +x setup.sh start.sh setup.command start.command ensure_venv.sh 2>/dev/null || true

echo "════════════════════════════════════════════"
echo "  TJSBOT — установка на Mac"
echo "  папка: $ROOT"
echo "════════════════════════════════════════════"
echo "Нужен интернет. Если спросит пароль Mac —"
echo "введи его (символы не отображаются) и Enter."
echo "════════════════════════════════════════════"

[[ "$(uname -s)" == "Darwin" ]] || fail "Нужен macOS."

# PATH для Apple Silicon и Intel
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

load_brew_env() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

# ── 1. Command Line Tools (нужны для brew/python) ────────
say "[1/7] Проверка инструментов разработчика (Xcode CLT)…"
if ! xcode-select -p >/dev/null 2>&1; then
  echo "  Ставлю Command Line Tools — откроется окно macOS."
  echo "  Дождись окончания установки, затем снова:"
  echo "    bash setup.sh"
  xcode-select --install 2>/dev/null || true
  fail "Сначала установи Command Line Tools в окне macOS, потом снова bash setup.sh"
fi
ok "CLT есть: $(xcode-select -p)"

# ── 2. Homebrew ──────────────────────────────────────────
say "[2/7] Homebrew…"
load_brew_env
if ! command -v brew >/dev/null 2>&1; then
  echo "  Ставлю Homebrew (первый раз ~5–15 мин)…"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || fail "Не удалось поставить Homebrew. Проверь интернет и пароль Mac."
  load_brew_env
  # чтобы brew был в новых окнах Терминала
  if [[ -x /opt/homebrew/bin/brew ]]; then
    touch "$HOME/.zprofile"
    if ! grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null; then
      {
        echo ''
        echo '# Homebrew (TJSBOT setup)'
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"'
      } >> "$HOME/.zprofile"
    fi
  fi
fi
command -v brew >/dev/null 2>&1 || fail "brew не найден после установки"
ok "brew: $(brew --prefix)"

# ── 3. Python 3.10+ ──────────────────────────────────────
say "[3/7] Python…"
find_python() {
  local cand ver major minor
  for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      # stub /usr/bin/python3 без CLT — отсекаем
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

PY="$(find_python || true)"
# Системный stub часто бесполезен — предпочитаем brew python
if [[ -z "$PY" || "$PY" == "/usr/bin/python3" ]]; then
  echo "  Ставлю python через Homebrew…"
  brew install python || fail "brew install python не удался"
  load_brew_env
  PY="$(find_python || true)"
fi
[[ -n "$PY" ]] || fail "Python 3.10+ так и не найден"
ok "Python: $PY ($("$PY" --version 2>&1))"

# ── 4. adb (телефон) ─────────────────────────────────────
say "[4/7] Android adb (для телефона)…"
if ! command -v adb >/dev/null 2>&1; then
  echo "  Ставлю android-platform-tools…"
  brew install android-platform-tools || fail "brew install android-platform-tools не удался"
  load_brew_env
fi
ok "adb: $(command -v adb)"

# ── 5. venv + pip ────────────────────────────────────────
say "[5/7] Виртуальное окружение и пакеты Python…"
[[ -f requirements.txt ]] || fail "Нет requirements.txt в $ROOT"

# .venv из zip с другого Mac часто битый — проверяем, что python реально работает
venv_ok() {
  [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys' >/dev/null 2>&1
}

if venv_ok; then
  ok ".venv уже есть — обновлю пакеты"
else
  if [[ -d .venv ]]; then
    echo "  .venv битый (часто после копирования с другого Mac) — пересоздаю…"
    rm -rf .venv
  fi
  "$PY" -m venv .venv || fail "Не удалось создать .venv"
  ok "создан .venv"
fi

VENV_PY="$ROOT/.venv/bin/python"
[[ -x "$VENV_PY" ]] || fail "нет $VENV_PY после создания venv"

"$VENV_PY" -m pip install --upgrade pip setuptools wheel
"$VENV_PY" -m pip install -r requirements.txt || fail "pip install -r requirements.txt не удался"
ok "зависимости из requirements.txt"

# ── 6. Playwright Chromium ───────────────────────────────
say "[6/7] Playwright Chromium (браузер для автоматизации)…"
"$VENV_PY" -m playwright install chromium || fail "playwright install chromium не удался"
# на Mac обычно хватает chromium; deps — на всякий случай
"$VENV_PY" -m playwright install-deps chromium 2>/dev/null || true
ok "Chromium установлен"

# ── 7. config ────────────────────────────────────────────
say "[7/7] Конфиг…"
if [[ ! -f config.yaml ]]; then
  if [[ -f config.example.yaml ]]; then
    cp config.example.yaml config.yaml
    ok "создан config.yaml из примера — потом поправь PIN и пути"
  else
    echo "  ⚠ нет config.example.yaml — добавь config.yaml вручную"
  fi
else
  ok "config.yaml уже есть — не трогаю"
fi

if [[ ! -f platcore-decline/config.yaml ]]; then
  if [[ -f platcore-decline/config.example.yaml ]]; then
    cp platcore-decline/config.example.yaml platcore-decline/config.yaml
    ok "создан platcore-decline/config.yaml — пропиши traders / browser profile"
  fi
else
  ok "platcore-decline/config.yaml уже есть — не трогаю"
fi

chmod +x setup.sh start.sh setup.command start.command ensure_venv.sh scripts/*.sh .githooks/* 2>/dev/null || true

if [[ -d .git ]]; then
  git config core.hooksPath .githooks
  ok "git hooks: VERSION бампается при push"
fi

echo ""
echo "════════════════════════════════════════════"
echo "  Готово. Дальше одна команда:"
echo ""
echo "    bash start.sh"
echo ""
echo "  Откроется http://127.0.0.1:8765"
echo "  Стоп: Ctrl+C в Терминале"
echo ""
echo "  Телефон: USB debugging → в UI «проверить»"
echo "  или: adb devices"
echo "════════════════════════════════════════════"
