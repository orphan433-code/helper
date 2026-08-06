# TODO — layout cleanup

## Сделано

- [x] Убрана обёртка `tzk/` — пакеты лежат в корне
- [x] Импорты: `from platcore...`, `from bank...`, …
- [x] `core.paths`: `ROOT`, `RUNTIME_DIR` (depth parents[1])
- [x] Shim из корня удалены; запуск через `-m ui` / `-m pipeline` / `-m bank`
- [x] `start.sh` → `python -m ui.browser`
- [x] Документы → `docs/`
- [x] Apple packaging → `macos/`
- [x] State JSON → `runtime/`
- [x] Пустые `cursor/`, `tools/`, `userscripts/` удалены
- [x] unittest 13/13 OK

## Follow-ups

- [ ] README install path уже ок; при желании сократить `УСТАНОВКА.txt`
- [ ] `macos/rebuild_app.sh` проверить сборку .app на живой машине
