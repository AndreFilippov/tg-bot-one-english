import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, Message

import config as cfg
from db import database
from db.repo import Repo
from handlers import chat, common, explain, lesson, review, settings, talk, test, words
from services.gemini import GeminiService
from services.scheduler import Reminders
from services.tts import TTSService

log = logging.getLogger("bot")


def setup_logging() -> None:
    cfg.LOGS_DIR.mkdir(exist_ok=True)
    handlers = [RotatingFileHandler(cfg.LOGS_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
                logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def install_access_filter(dp: Dispatcher, allowed_id: int) -> None:
    """Чужих пользователей молча игнорируем: хендлеры для них не вызываются."""
    async def only_owner(handler, event: Message | CallbackQuery, data):
        user = event.from_user
        if user is None or user.id != allowed_id:
            return None
        return await handler(event, data)

    dp.message.outer_middleware(only_owner)
    dp.callback_query.outer_middleware(only_owner)


async def main() -> None:
    setup_logging()
    config = cfg.load_config()
    cfg.DATA_DIR.mkdir(exist_ok=True)

    db = await database.connect(cfg.DB_PATH)
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    if config.access_check:
        install_access_filter(dp, config.allowed_user_id)
    else:
        log.warning("Проверка по Telegram ID ВЫКЛЮЧЕНА: бот отвечает всем (включить: ACCESS_CHECK=on в .env)")
    dp["config"] = config
    dp["repo"] = Repo(db)
    dp["gemini"] = GeminiService(config.gemini_api_key, config.gemini_model, config.gemini_thinking,
                                  list(config.gemini_fallback_models))
    dp["tts"] = TTSService(cfg.TTS_CACHE_DIR)
    reminders = Reminders(bot, dp["repo"], config.timezone)
    dp["reminders"] = reminders
    # common первым: /start и /cancel работают в любом состоянии
    dp.include_routers(common.router, settings.router, talk.router, lesson.router, review.router,
                       chat.router, explain.router, words.router, test.router)

    await bot.set_my_commands([
        BotCommand(command="talk", description="Голосовой разговор"),
        BotCommand(command="lesson", description="Урок на сегодня"),
        BotCommand(command="chat", description="Переписка на английском"),
        BotCommand(command="explain", description="Объяснить правило"),
        BotCommand(command="words", description="Словарь и повторение"),
        BotCommand(command="test", description="Проверка по темам"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="cancel", description="Выйти из режима"),
        BotCommand(command="start", description="Начало")])
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
