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

## Decline / редирект

`platcore-decline/` внутри репо.
Скопируй `config.example.yaml` → `config.yaml`, traders + browser profile.

## В git не кладём

- `.venv`, `config.yaml`, `platcore-decline/config.yaml`, `.env`
