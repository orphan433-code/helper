# helper

Для установки нужен интернет. Аккаунт на GitHub не требуется. Если система спросит пароль Mac — введи его (символы в Терминале не отображаются) и нажми Enter.

Сначала ставятся Homebrew и Git (ещё без папки проекта), затем скачивается код и запускается установка.

---

## Подготовка: Homebrew и Git

Открой приложение «Терминал» и выполни команды по очереди.

Установка Homebrew (если его ещё нет). Первый раз может занять 5–15 минут:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

На Mac с чипом Apple (M1 / M2 / M3 / M4) один раз добавь Homebrew в PATH:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Установи Git и проверь, что он работает:

```bash
brew install git
git --version
```

В ответе должна быть строка вроде `git version 2.x`. Если Homebrew уже был установлен раньше, достаточно только `brew install git`.

---

## Установка проекта

```bash
cd ~/Desktop
git clone https://github.com/orphan433-code/helper.git TJSBOT
cd TJSBOT
bash setup.sh
```

Дождись сообщения «Готово». После этого положи поверх готовые конфиги от коллеги (или поправь созданные из примера):

- `config.yaml`
- `platcore-decline/config.yaml`

Первый запуск:

```bash
bash start.sh
```

В браузере откроется адрес http://127.0.0.1:8765. Остановка сервера: `Ctrl+C` в окне Терминала.

### Если Git ставить не хочется

1. Открой страницу репозитория (ссылку даст коллега)
2. Нажми зелёную кнопку Code, затем Download ZIP
3. Распакуй архив на Рабочий стол и переименуй папку в `TJSBOT`
4. В Терминале:

```bash
cd ~/Desktop/TJSBOT
bash setup.sh
bash start.sh
```

Скрипт `setup.sh` при необходимости доустановит Homebrew и Git сам.

---

## Ежедневный запуск

```bash
cd ~/Desktop/TJSBOT && bash start.sh
```

Либо дважды кликни файл `start.command` в папке TJSBOT. Остановка: `Ctrl+C`.

---

## Обновления

В верхней панели интерфейса нажми кнопку со стрелкой вниз (скачать обновление). Когда закончится — кнопку перезапуска рядом. Файл `config.yaml` при обновлении не перезаписывается.

---

## Структура кода

Пакеты в корне: `platcore/`, `bank/`, `device/`, `notify/`, `completion/`, `ui/`, `core/`, `pipeline/`.  
Запуск: `bash start.sh` → `python -m ui.browser`.  
Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Локальные файлы

В репозиторий не попадают:

- `.venv`
- `config.yaml`
- `platcore-decline/config.yaml`
- `.env`
- `runtime/`
