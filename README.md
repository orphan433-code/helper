# TJSBOT — установка на новый Mac

Нужен интернет и пароль Mac (если спросит). Аккаунт GitHub **не нужен**.

Порядок такой: **сначала brew + git** (ещё без папки проекта) → потом clone → setup.

## 0. Homebrew и Git (до скачивания проекта)

Открой **Терминал** и по очереди:

```bash
# 1) Homebrew (если ещё нет; первый раз ~5–15 мин, спросит пароль Mac)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2) PATH для Apple Silicon (M1/M2/M3) — один раз:
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"

# 3) Git
brew install git
git --version
```

Должно показать `git version 2.…`.  
Если brew уже был — достаточно `brew install git`.

## 1. Скачать проект

```bash
cd ~/Desktop
git clone https://github.com/orphan433-code/helper.git TJSBOT
cd TJSBOT
bash setup.sh
```

Дождись «Готово». Поправь `config.yaml` (PIN) или положи готовые конфиги от коллеги поверх.

```bash
bash start.sh
```

Откроется http://127.0.0.1:8765 — стоп: `Ctrl+C`.

### Без git (запасной путь)

В браузере: https://github.com/orphan433-code/helper → зелёная **Code** → **Download ZIP** → распакуй на Рабочий стол как `TJSBOT` → в Терминале:

```bash
cd ~/Desktop/TJSBOT
bash setup.sh
bash start.sh
```

(`setup.sh` при необходимости сам доставит brew/git; обновления кнопкой **↓** работают и без локального git — качает ZIP.)

## Обновления

В шапке UI кнопка **↓** → потом **↻**.  
`config.yaml` не затирается.

## В git не кладём

- `.venv`, `config.yaml`, `platcore-decline/config.yaml`, `.env`
