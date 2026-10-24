# My English — личный Telegram-бот для изучения американского английского (A1)

Бот говорит голосом, вы отвечаете голосовым, он распознаёт речь, мягко исправляет ошибки и ведёт по программе A1.
Проверка по Telegram ID управляется переменной `ACCESS_CHECK` в `.env`: при `on` бот отвечает только пользователю `ALLOWED_USER_ID` и молча игнорирует остальных. **Сейчас по умолчанию проверка выключена (`off`)**: бот отвечает любому, кто его найдёт, и тратит вашу квоту Gemini. Перед запуском на сервере включите `ACCESS_CHECK=on`.

## Возможности

| Команда | Что делает |
|---|---|
| `/start` | знакомство, тест уровня (7 вопросов), рассказ о себе (имя, город, занятие, цель, интересы), время напоминания |
| `/talk` | **голосовой разговор** по сценарию (знакомство, кафе, магазин, дорога, о себе, семья, день, погода, хобби, свободная тема, **⭐ мои интересы**) |
| `/lesson` | ежедневный урок: повторение слов → грамматика → 5 фраз на перевод → голосовой мини-диалог |
| `/chat` | переписка текстом, исправления в конце сообщения |
| `/repeat` | **«повтори за мной»**: бот произносит фразу, вы повторяете голосом, он оценивает произношение (1–5) |
| `/listen` | **аудирование**: короткая история голосом и 3 вопроса с вариантами ответа |
| `/translate [текст]` | переводчик: текст или голосовое, RU↔EN; английский вариант озвучивается, можно добавить в словарь |
| `/explain <вопрос>` | объяснение правила по-русски |
| `/words` | словарь, статистика, «Повторить сейчас», прослушивание слов |
| `/add слово перевод` | добавить слово (`/add apple`: перевод и пример найдёт ИИ); `/due слово` — поставить на повторение сейчас |
| `/export`, `/import` | словарь в CSV и обратно |
| `/weak` | ваши самые частые ошибки и тренировка на них |
| `/test` | проверка по пройденным темам (раз в неделю) |
| `/progress` | уровень, тема, серия дней, дневная цель, неделя, слова, точность по темам, запросы к Gemini за день |
| `/level` | сменить уровень: тест A1+A2, выбор темы вручную, переход A1 ↔ A2 |
| `/profile` | что бот помнит о вас: имя, город, занятие, цель, интересы, факты (можно править и удалять) |
| `/settings` | голос, скорость, показ текста, время напоминания, цель дня, роль собеседника, объяснения по-русски/по-английски |
| `/reset` | сброс словаря, прогресса, профиля или всего (с подтверждением) |
| `/cancel` | выйти из текущего режима |
| `/allow`, `/deny`, `/users`, `/backup` | только админ (первый ID в `ALLOWED_USER_ID`) |

**Память бота.** Профиль (имя, интересы, факты) подставляется в промпты: бот не переспрашивает известное и ведёт разговоры на ваши темы. После разговора он предлагает запомнить новые факты о вас (кнопкой). Режим, в котором вы находитесь (урок, разговор), сохраняется в базе и переживает перезапуск бота.

**Прогресс.** Дневная цель считается в очках: слово в повторении, ответ в упражнении, сообщение в чате = 1 очко, реплика в разговоре = 2. Серия — число дней подряд с выполненной целью. В напоминании бот пишет серию и сегодняшний прогресс, а по воскресеньям присылает недельную сводку.

**Уровни.** Программа: A1 (33 темы) и A2 (20 тем), файлы `data/curriculum_a1.yaml`, `data/curriculum_a2.yaml`. Переход к следующей теме — только если в упражнениях урока 80%+ верных ответов (4 из 5). Новые слова из разговоров автоматически попадают в словарь и повторяются по упрощённому SM-2.

**Резервные копии.** Каждую ночь (04:00 по `TIMEZONE`) бот копирует `data/bot.db` в `data/backups/` (хранится 7 последних). По воскресеньям копия приходит админу в Telegram (`BACKUP_TO_TELEGRAM=off` отключает). Админ может получить копию командой `/backup`. Восстановление: остановите бота и замените `data/bot.db` файлом копии.

## 1. Что понадобится

1. **Python 3.11+** (проверка: `python --version`).
2. **ffmpeg** (нужен, чтобы превращать озвучку в голосовые сообщения Telegram).
3. **Токен бота**: в Telegram откройте [@BotFather](https://t.me/BotFather) → `/newbot` → придумайте имя → скопируйте токен.
4. **Ключ Gemini**: https://aistudio.google.com/apikey → *Create API key*.
5. **Ваш Telegram ID**: напишите боту [@userinfobot](https://t.me/userinfobot), он пришлёт число.

### Установка ffmpeg

- **Windows**: `winget install Gyan.FFmpeg` (затем откройте новое окно терминала) или скачайте сборку с https://www.gyan.dev/ffmpeg/builds/ и добавьте папку `bin` в `PATH`.
- **macOS**: `brew install ffmpeg`
- **Linux (Debian/Ubuntu)**: `sudo apt update && sudo apt install -y ffmpeg`

Проверка: `ffmpeg -version`.

## 2. Установка и запуск

```bash
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Windows (Git Bash):    source .venv/Scripts/activate
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # Windows: copy .env.example .env
# откройте .env и заполните значения
python bot.py
```

Настройки `.env`:

| Переменная | Значение |
|---|---|
| `BOT_TOKEN` | токен от BotFather |
| `GEMINI_API_KEY` | ключ Gemini |
| `GEMINI_MODEL` | модель, например `gemini-3.5-flash` (см. ниже) |
| `ACCESS_CHECK` | `on` — отвечать только `ALLOWED_USER_ID`; `off` (по умолчанию) — отвечать всем |
| `ALLOWED_USER_ID` | ваш Telegram ID (обязателен при `ACCESS_CHECK=on`); можно несколько через запятую, первый — админ. Остальных админ добавляет командой `/allow <id>` |
| `BACKUP_TO_TELEGRAM` | `on` (по умолчанию) — присылать админу еженедельную копию базы |
| `TTS_VOICE` | голос по умолчанию, `en-US-AriaNeural` |
| `GEMINI_THINKING` | уровень «размышлений»: `low` / `medium` / `high`; пусто — не передавать |
| `GEMINI_FALLBACK_MODELS` | запасные модели через запятую (по умолчанию `gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.5-flash`) |
| `TIMEZONE` | ваш часовой пояс для напоминаний, например `Europe/Moscow` |

Откройте бота в Telegram и отправьте `/start`. Логи: `logs/bot.log`.

### Как выбрать модель Gemini

Доступность моделей зависит от вашего ключа и тарифа. Запустите проверку:

```bash
python check_gemini.py
```

Она покажет, какие Flash-модели вам доступны. Берите стабильную без `-preview`, которая отвечает `[OK]`. На бесплатном тарифе у Lite-моделей лимит около 500 запросов в сутки и 15 в минуту, у обычных Flash всего 20 в сутки и 5 в минуту (актуальные цифры: https://ai.dev/rate-limit), поэтому основной лучше выбрать Lite. Для коротких реплик A1 подойдут и «lite»-модели.

## 3. Тесты

```bash
python -m pytest
```

Проверяют SRS, разбор JSON, конвертацию аудио в ogg/opus, базу и сквозные сценарии (онбординг, урок, чат, настройки, тест) на поддельных Telegram и ИИ. Тесты ffmpeg пропускаются, если его нет.

## 4. Запуск на сервере (круглосуточно)

Нужен любой VPS с Linux (Ubuntu 22.04+). Бот сам опрашивает Telegram, открытые порты и домен не нужны.

### Вариант A: systemd (рекомендуется)

```bash
sudo apt update && sudo apt install -y python3 python3-venv ffmpeg git
sudo useradd -m -s /bin/bash english
sudo -iu english
git clone <ваш-репозиторий> my-english    # или скопируйте папку через scp/rsync
cd my-english
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env         # заполните ключи
exit
```

Установите службу (файл `deploy/my-english.service` лежит в проекте; проверьте в нём пути и пользователя):

```bash
sudo cp /home/english/my-english/deploy/my-english.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now my-english
sudo systemctl status my-english          # должно быть active (running)
journalctl -u my-english -f               # живые логи; файл логов: logs/bot.log
```

Обновление: `git pull`, затем `.venv/bin/pip install -r requirements.txt`, затем `sudo systemctl restart my-english`.
Резервная копия: файл `data/bot.db` (словарь и прогресс).

### Вариант B: Docker

```bash
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f
```

База и логи сохраняются в папках `data/` и `logs/` рядом с проектом.

## 5. Частые проблемы

- **`VOICE_MESSAGES_FORBIDDEN`** — в Telegram запрещены голосовые сообщения: *Настройки → Конфиденциальность → Голосовые сообщения → Все* (раздел может требовать Premium). Пока запрет действует, бот шлёт озвучку аудиофайлом.
- **403 `PERMISSION_DENIED` от Gemini** — выбранная модель недоступна вашему ключу. Запустите `python check_gemini.py` и поменяйте `GEMINI_MODEL`.
- **404 `no longer available`** — модель отключена, выберите другую.
- **400 `Thinking level ... not supported`** — задайте другой `GEMINI_THINKING` или оставьте пустым.
- **429 `PerDay`, «дневной лимит»** — на бесплатном тарифе у каждой модели свой лимит запросов в сутки (у некоторых моделей всего 20). Бот сам переключается на модели из `GEMINI_FALLBACK_MODELS`; если исчерпаны все, лимит сбросится через несколько часов (бот пишет, через сколько). Урок и разговор тратят около 10–12 запросов, поэтому для ежедневных занятий лучше подключить оплату в AI Studio или смотреть лимиты на https://ai.dev/rate-limit.
- **429 «в минуту»** — исчерпан лимит бесплатного тарифа. Бот сам повторяет запрос с нарастающей паузой; если не помогло, подождите минуту.
- **Бот не отвечает** — если `ACCESS_CHECK=on`, проверьте `ALLOWED_USER_ID` (чужим бот не отвечает намеренно) и `logs/bot.log`.
- **`ffmpeg` не найден** — установите его и перезапустите терминал.

## 6. Структура проекта

```
bot.py               точка входа
config.py            настройки из .env
handlers/            команды: common, talk, lesson, review, chat, explain, words, vocab, test, weak, pronounce,
                     listen, translate, profile, progress, settings, reset, admin
services/            gemini (запасные модели, счётчик запросов), tts (edge-tts + кеш), audio (ffmpeg), srs, curriculum,
                     profile, progress (серия), scheduler, backup, sqlite_storage (режимы в БД), vocab_io, ...
db/                  SQLite: схема, миграции, запросы
prompts/             системные промпты (*.txt)
data/                curriculum_a1.yaml, curriculum_a2.yaml, scenarios.yaml, placement_test.yaml, pronunciation.yaml,
                     bot.db, backups/, tts_cache/
tests/               автотесты
deploy/              systemd-служба
```

Новый сценарий для `/talk` — добавьте блок в `data/scenarios.yaml`. Новую тему — в `data/curriculum_a1.yaml` или `curriculum_a2.yaml`, фразу для `/repeat` — в `data/pronunciation.yaml`.
