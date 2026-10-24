import asyncio
import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, CallbackQuery, FSInputFile, Message

import config as cfg
from db import database
from db.repo import Repo
from handlers import (admin, chat, common, explain, lesson, listen, profile, progress, pronounce, reset, review,
                      settings, talk, test, translate, vocab, weak, words)
from services import backup, clock
from services.gemini import GeminiService
from services.scheduler import Reminders
from services.sqlite_storage import SqliteStorage
from services.tts import TTSService

log = logging.getLogger("bot")

COMMANDS = [
    ("talk", "Голосовой разговор"), ("lesson", "Урок на сегодня"), ("chat", "Переписка на английском"),
    ("repeat", "Повтори за мной (произношение)"), ("listen", "Аудирование"), ("translate", "Переводчик"),
    ("explain", "Объяснить правило"), ("words", "Словарь и повторение"), ("weak", "Мои слабые места"),
    ("test", "Проверка по темам"), ("progress", "Прогресс"), ("level", "Сменить уровень или тему"),
    ("profile", "Что бот помнит обо мне"), ("settings", "Настройки"), ("reset", "Сброс данных"),
    ("cancel", "Выйти из режима"), ("start", "Начало"),
]


def setup_logging() -> None:
    cfg.LOGS_DIR.mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(cfg.LOGS_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
                logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def install_access_filter(dp: Dispatcher, config: cfg.Config, repo: Repo) -> None:
    """Чужих пользователей молча игнорируем: хендлеры для них не вызываются."""
    async def only_allowed(handler, event: Message | CallbackQuery, data):
        user = event.from_user
        if user is None:
            return None
        if user.id not in config.allowed_user_ids and not await repo.is_allowed(user.id):
            return None
        return await handler(event, data)

    dp.message.outer_middleware(only_allowed)
    dp.callback_query.outer_middleware(only_allowed)


async def main() -> None:
    setup_logging()
    config = cfg.load_config()
    cfg.DATA_DIR.mkdir(exist_ok=True)
    clock.configure(config.timezone)

    db = await database.connect(cfg.DB_PATH)
    repo = Repo(db)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=SqliteStorage(db))  # режим (урок, разговор…) переживает перезапуск
    if config.access_check:
        install_access_filter(dp, config, repo)
    else:
        log.warning("Проверка по Telegram ID ВЫКЛЮЧЕНА: бот отвечает всем (включить: ACCESS_CHECK=on в .env)")
    dp["config"] = config
    dp["repo"] = repo
    dp["gemini"] = GeminiService(config.gemini_api_key, config.gemini_model, config.gemini_thinking,
                                 list(config.gemini_fallback_models), usage_hook=repo.add_api_usage)
    dp["tts"] = TTSService(cfg.TTS_CACHE_DIR)
    reminders = Reminders(bot, repo, config.timezone)
    dp["reminders"] = reminders
    # common первым: /start и /cancel работают в любом состоянии
    dp.include_routers(common.router, settings.router, profile.router, progress.router, talk.router, lesson.router,
                       review.router, chat.router, explain.router, words.router, test.router, weak.router,
                       pronounce.router, listen.router, translate.router, vocab.router, reset.router, admin.router)

    async def backup_job() -> None:
        with contextlib.suppress(Exception):
            await backup.make_backup(cfg.DB_PATH, cfg.BACKUP_DIR)

    async def weekly_backup_to_admin() -> None:
        if not (config.backup_to_telegram and config.allowed_user_ids):
            return
        try:
            path = await backup.make_backup(cfg.DB_PATH, cfg.BACKUP_DIR)
            await bot.send_document(config.allowed_user_ids[0], FSInputFile(path), caption="💾 Еженедельная копия базы")
        except Exception:
            log.exception("Не удалось отправить резервную копию")

    reminders.add_cron(backup_job, "backup_daily", hour=4)
    reminders.add_cron(weekly_backup_to_admin, "backup_weekly", hour=10, day_of_week="sun")

    await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
    await reminders.start()
    log.info("Bot started, model=%s", config.gemini_model)
    try:
        await dp.start_polling(bot)
    finally:
        reminders.scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
