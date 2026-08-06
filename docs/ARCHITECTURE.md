# Архитектура TJSBOT

Код лежит **пакетами в корне репо** — без лишней обёртки `tzk/`.

## Дерево (как должно выглядеть)

```
TJSBOT/
├── platcore/          # Playwright: список, accept, pending, dispute, completion
├── bank/              # Activ Bank: PIN → nav → form → confirm → receipt
├── device/            # adb, OCR, softkey, screenshot, clicker, media
├── notify/            # SMS + отмены в шторке
├── completion/        # загрузка чеков / batch
├── ui/                # browser (FastAPI), web (pywebview), gui (Tk)
├── core/              # config, models, paths, session, validators…
├── pipeline/          # оркестратор accept → bank → complete
│
├── web_ui/            # статика интерфейса
├── platcore-decline/  # отдельный подпроект
├── tests/
├── scripts/           # git hooks, bump version
├── docs/              # ARCHITECTURE, TODO, установка
├── macos/             # .app / entitlements / launcher
├── runtime/           # локальный state (gitignored)
│
├── start.sh / setup.sh / start.command / setup.command
├── config.yaml / config.example.yaml
├── requirements.txt / README.md / VERSION / update.json
└── ensure_venv.sh
```

## Запуск

```bash
bash start.sh                      # → python -m ui.browser  (:8765)
.venv/bin/python -m ui             # то же
.venv/bin/python -m pipeline       # консольный цикл
.venv/bin/python -m bank           # только банк
```

## Главный поток

```
pipeline.runner.run_pipeline
  → platcore.pipeline.accept_deals_loop
     ИЛИ platcore.pending.claim_pending_deals_loop
  → (опц.) bank.flow
  → completion.phase
Параллельно: notify.cancel
```

Пути к конфигу / web_ui / runtime — через `core.paths.ROOT` и `RUNTIME_DIR`.

## Куда класть новое

| Что добавляешь | Куда |
|---|---|
| Логика PlatCore | `platcore/` |
| Шаги банка | `bank/` |
| ADB / OCR / тапы | `device/` |
| Watcher уведомлений | `notify/` |
| Чеки / batch | `completion/` |
| UI / API кнопки | `ui/` |
| Ключ config | `core/config.py` + `config.example.yaml` |
| Оркестрация | `pipeline/runner.py` |
| Документация | `docs/` |
| Сборка .app | `macos/` |
