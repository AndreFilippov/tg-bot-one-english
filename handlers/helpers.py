import html
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message, User

from config import Config
from db.repo import Repo
from services import curriculum
from services.audio import AudioError
from services.gemini import GeminiError, GeminiRateLimit
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)


def error_text(e: Exception) -> str:
    if isinstance(e, GeminiRateLimit) and e.daily:
        wait = f" Лимит сбросится примерно через {max(1, round(e.retry_in / 3600))} ч." if e.retry_in else ""
        return ("⏳ Дневной лимит бесплатного тарифа Gemini исчерпан на всех моделях." + wait +
                "\nМожно добавить другие модели в GEMINI_FALLBACK_MODELS (.env) или подключить оплату в AI Studio.")
    if isinstance(e, GeminiRateLimit):
        return "⏳ Лимит бесплатного тарифа Gemini исчерпан. Подождите минуту и попробуйте ещё раз."
    if isinstance(e, GeminiError):
        return "😕 Не получилось связаться с ИИ. Попробуйте ещё раз через минуту."
    if isinstance(e, AudioError):
        return "😕 Не удалось подготовить аудио (проверьте, что установлен ffmpeg)."
    return "😕 Что-то пошло не так. Попробуйте ещё раз."


async def get_user(repo: Repo, tg_user: User, config: Config) -> dict:
    return await repo.get_or_create_user(tg_user.id, tg_user.full_name, config.tts_voice)


async def build_system(repo: Repo, user: dict, topic_id: str | None = None) -> str:
    topic = curriculum.topic_by_id(topic_id or user["current_topic"])
    mistakes = await repo.recent_mistakes(user["user_id"])
    words = await repo.sample_words(user["user_id"])
    return render(
        "system_teacher",
        topic=f"{topic['title']} ({topic['focus']})",
        mistakes="; ".join(f"{m['wrong']} -> {m['right']}" for m in mistakes) or "none yet",
        words=", ".join(words) or "none yet",
    )


async def say(message: Message, tts: TTSService, user: dict, text: str, *, rate: int | None = None,
              caption_prefix: str = "", markup: InlineKeyboardMarkup | None = None,
              show_text: bool | None = None) -> None:
    """Отправляет озвученную фразу голосовым. Английский текст — под спойлером (если включён в настройках)."""
    path = await tts.synth(text, user["voice"], user["speech_rate"] if rate is None else rate)
    caption = caption_prefix
    if user["show_text"] if show_text is None else show_text:
        caption += f"<tg-spoiler>{html.escape(text)}</tg-spoiler>"
    try:
        await message.answer_voice(FSInputFile(path), caption=caption or None, reply_markup=markup)
    except TelegramBadRequest as e:
        if "VOICE_MESSAGES_FORBIDDEN" not in str(e):
            raise
        # В приватности Telegram запрещены голосовые сообщения: шлём как обычный аудиофайл
        log.warning("Голосовые запрещены настройками приватности, отправляю как аудиофайл")
        await message.answer("⚠️ Telegram не даёт отправить голосовое: Настройки → Конфиденциальность → "
                             "Голосовые сообщения → разрешите «Все». Пока отправляю аудиофайлом.")
        await message.answer_audio(FSInputFile(path), caption=caption or None, reply_markup=markup)
