# TJSBOT — установка на новый Mac

Нужен интернет и пароль Mac (если спросит). Аккаунт GitHub **не нужен**.

## Первый раз

```bash
cd ~/Desktop
git clone https://github.com/orphan433-code/helper.git TJSBOT
cd TJSBOT
bash setup.sh
```

Дождись «Готово». Поправь `config.yaml` (PIN, пути) — создаётся из примера.

```bash
bash start.sh
```

Откроется http://127.0.0.1:8765 — стоп: `Ctrl+C`.

## Обновления

В шапке UI кнопка **↓** — скачает код с [helper](https://github.com/orphan433-code/helper)
и соберёт/обновит `.venv`. Потом **↻**.

`config.yaml` не затирается.

В UI сверху видно `v…` из файла `VERSION`. При `git push` версия **сама** становится сегодняшней датой (`2026.08.01`, следующий пуш за день — `.2`, `.3`…).

## Decline / редирект

`platcore-decline/` внутри репо.
При первом запуске `config.yaml` создаётся сам из `config.example.yaml`.
Поправь там:
- **browser profile** — путь к папке Chromium с логином PlatCore
- **traders** — label + UUID аккаунтов для редиректа (кнопки 104.1 / 104.2)

## В git не кладём

- `.venv`, `config.yaml`, `platcore-decline/config.yaml`, `.env`
