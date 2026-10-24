import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers import review
from handlers.helpers import error_text, get_user, say
from services.gemini import GeminiService
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()
PAGE = 8


def main_kb(due: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔁 Повторить сейчас ({due})", callback_data="w:review")],
        [InlineKeyboardButton(text="📖 Список слов", callback_data="w:list:0")],
    ])


@router.message(Command("words"))
async def cmd_words(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    s = await repo.word_stats(user["user_id"])
    await message.answer(
        "📚 <b>Мой словарь</b>\n"
        f"Всего слов: {s['total']}\nНа повторение сейчас: {s['due']}\n"
        f"Выучено (интервал от 21 дня): {s['learned']}\n\n"
        "<i>Новые слова добавляются после разговоров (/talk).</i>",
        reply_markup=main_kb(s["due"]))


@router.callback_query(F.data == "w:review")
async def on_review(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                    config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await state.clear()
    await review.start_review(cb.message, state, repo, gemini, tts, user)


@router.callback_query(F.data.startswith("w:list:"))
async def on_list(cb: CallbackQuery, repo: Repo) -> None:
    await cb.answer()
    page = int(cb.data.split(":")[2])
    words = await repo.list_words(cb.from_user.id, page * PAGE, PAGE + 1)
    has_next = len(words) > PAGE
    words = words[:PAGE]
    if not words:
        await cb.message.answer("Словарь пока пуст. Поговорите в /talk — новые слова добавятся сами.")
        return
    text = "\n".join(f"• <b>{html.escape(w['word'])}</b> — {html.escape(w['translation'])}" for w in words)
    rows = [[InlineKeyboardButton(text=f"🔊 {w['word']}", callback_data=f"wa:{w['id']}")] for w in words]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"w:list:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"w:list:{page + 1}"))
    if nav:
        rows.append(nav)
    await cb.message.answer(f"📖 <b>Слова, страница {page + 1}</b>\n{text}",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("wa:"))
async def on_listen(cb: CallbackQuery, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    word = await repo.get_word(int(cb.data[3:]))
    if not word:
        return
    user = await get_user(repo, cb.from_user, config)
    caption = f"<b>{html.escape(word['word'])}</b> — {html.escape(word['translation'])}"
    if word["example"]:
        caption += f"\n<i>{html.escape(word['example'])}</i>"
    try:
        await say(cb.message, tts, user, word["word"], show_text=False, caption_prefix=caption)
    except Exception as e:
        log.exception("word tts failed")
        await cb.message.answer(error_text(e))
