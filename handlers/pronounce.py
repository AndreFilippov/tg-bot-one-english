"""/repeat — «повтори за мной»: бот произносит фразу, вы повторяете голосом, он оценивает произношение."""
import html
import logging
import random

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, say, track
from services import curriculum, profile
from services.audio import download_voice
from services.gemini import GeminiService
from services.models import PronunciationCheck
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()
SLOW_RATE = -35


class Pron(StatesGroup):
    waiting = State()


def kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐢 Медленнее", callback_data="pr:slow"),
         InlineKeyboardButton(text="🔁 Ещё раз", callback_data="pr:again")],
        [InlineKeyboardButton(text="⏭ Другая фраза", callback_data="pr:next"),
         InlineKeyboardButton(text="⏹ Стоп", callback_data="pr:stop")],
    ])


async def pick_phrase(repo: Repo, user_id: int, previous: str | None = None) -> dict:
    """Фраза из data/pronunciation.yaml; иногда — пример из вашего словаря."""
    if random.random() < 0.3:
        examples = [w["example"] for w in await repo.all_words(user_id) if 2 <= len((w["example"] or "").split()) <= 9]
        if examples:
            return {"text": random.choice(examples), "focus": "примеры из вашего словаря"}
    pool = [p for p in curriculum.load_pronunciation() if p["text"] != previous]
    return random.choice(pool)


async def send_phrase(message: Message, state: FSMContext, tts: TTSService, user: dict, phrase: dict,
                      rate: int | None = None) -> None:
    await state.set_state(Pron.waiting)
    await state.update_data(phrase=phrase["text"], focus=phrase["focus"])
    caption = (f"🎤 Повторите вслух:\n<b>{html.escape(phrase['text'])}</b>\n"
               f"<i>Обратите внимание: {html.escape(phrase['focus'])}</i>\n")
    try:
        await say(message, tts, user, phrase["text"], rate=rate, caption_prefix=caption, show_text=False, markup=kb())
    except Exception as e:
        log.exception("pronounce tts failed")
        await message.answer(f"{caption}\n{error_text(e)}", reply_markup=kb())


@router.message(Command("repeat"))
async def cmd_repeat(message: Message, state: FSMContext, repo: Repo, tts: TTSService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    await message.answer("🎤 <b>Повтори за мной</b>. Слушайте фразу и отвечайте голосовым — "
                         "я оценю произношение. Выход: /cancel")
    await send_phrase(message, state, tts, user, await pick_phrase(repo, user["user_id"]))


@router.message(Pron.waiting, F.voice)
async def on_voice(message: Message, bot: Bot, state: FSMContext, repo: Repo, gemini: GeminiService,
                   config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    data = await state.get_data()
    try:
        audio = await download_voice(bot, message.voice.file_id)
        result = await gemini.generate_json(
            PronunciationCheck, render("pronounce_check", phrase=data["phrase"], explain_lang=profile.explain_lang(user)),
            await build_system(repo, user), audio=audio)
    except Exception as e:
        log.exception("pronunciation check failed")
        await message.answer(error_text(e))
        return
    if not result.recognized:
        await message.answer("🙉 Не расслышал(а). Повторите ещё раз чётко и не спеша.")
        return
    score = max(1, min(5, result.score or 1))
    lines = [f"{'⭐' * score}{'☆' * (5 - score)}  <b>{score}/5</b>",
             f"Я услышал: <i>{html.escape(result.transcript)}</i>"]
    if result.issues:
        lines.append("\n" + "\n".join(f"• {html.escape(i)}" for i in result.issues))
    if result.tip:
        lines.append(f"\n💡 {html.escape(result.tip)}")
    await message.answer("\n".join(lines), reply_markup=kb())
    await track(repo, message, user["user_id"], 2)


@router.message(Pron.waiting, F.text & ~F.text.startswith("/"))
async def on_text(message: Message) -> None:
    await message.answer("Здесь нужен голос: запишите голосовое сообщение с этой фразой 🎙")


async def _current(state: FSMContext) -> dict:
    d = await state.get_data()
    return {"text": d["phrase"], "focus": d["focus"]}


@router.callback_query(Pron.waiting, F.data.in_({"pr:slow", "pr:again"}))
async def on_replay(cb: CallbackQuery, state: FSMContext, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await send_phrase(cb.message, state, tts, user, await _current(state),
                      rate=SLOW_RATE if cb.data == "pr:slow" else None)


@router.callback_query(Pron.waiting, F.data == "pr:next")
async def on_next(cb: CallbackQuery, state: FSMContext, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    current = await _current(state)
    await send_phrase(cb.message, state, tts, user, await pick_phrase(repo, user["user_id"], current["text"]))


@router.callback_query(Pron.waiting, F.data == "pr:stop")
async def on_stop(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await cb.message.answer("Хорошая тренировка! 👏 /repeat — ещё раз, /talk — разговор.")
