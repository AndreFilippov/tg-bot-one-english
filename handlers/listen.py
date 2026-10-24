"""/listen — аудирование: бот рассказывает короткую историю голосом, вы отвечаете на вопросы кнопками."""
import html
import logging
import random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, say, track
from services import curriculum, profile
from services.gemini import GeminiService
from services.models import ListenSet
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()
SLOW_RATE = -30


class Listen(StatesGroup):
    active = State()


def story_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐢 Медленнее", callback_data="lis:slow"),
         InlineKeyboardButton(text="📜 Показать текст", callback_data="lis:text")],
        [InlineKeyboardButton(text="▶️ К вопросам", callback_data="lis:go")],
    ])


@router.message(Command("listen"))
async def cmd_listen(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                     config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    interests = profile.interests_of(user)
    topic = random.choice(interests) if interests else "everyday life"
    grammar = curriculum.topic_by_id(user["current_topic"])
    await message.answer("🎧 <b>Аудирование</b>. Слушайте историю, потом ответьте на 3 вопроса.\n⏳ Готовлю…")
    try:
        data = await gemini.generate_json(
            ListenSet, render("listen", topic=topic, grammar=f"{grammar['title']} ({grammar['focus']})"),
            await build_system(repo, user))
        questions = [q.model_dump() for q in data.questions
                     if len(q.options) == 3 and 0 <= q.answer < 3][:3]
        if not data.story.strip() or not questions:
            raise ValueError("bad listening set")
    except Exception as e:
        log.exception("listen generation failed")
        await message.answer(error_text(e))
        return
    await state.set_state(Listen.active)
    await state.update_data(story=data.story, qs=questions, qi=0, qc=0)
    try:
        await say(message, tts, user, data.story, show_text=False, markup=story_kb(),
                  caption_prefix="🎧 Слушайте внимательно. Текст скрыт — можно показать кнопкой.")
    except Exception as e:
        log.exception("listen tts failed")
        await state.clear()
        await message.answer(error_text(e))


@router.callback_query(Listen.active, F.data == "lis:slow")
async def on_slow(cb: CallbackQuery, state: FSMContext, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    data = await state.get_data()
    try:
        await say(cb.message, tts, user, data["story"], rate=SLOW_RATE, show_text=False, markup=story_kb(),
                  caption_prefix="🐢 Медленнее")
    except Exception as e:
        log.exception("slow tts failed")
        await cb.message.answer(error_text(e))


@router.callback_query(Listen.active, F.data == "lis:text")
async def on_text(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.answer(f"📜 {html.escape((await state.get_data())['story'])}")


@router.callback_query(Listen.active, F.data == "lis:go")
async def on_go(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    await ask(cb.message, data["qs"], data["qi"])


async def ask(message: Message, qs: list[dict], i: int) -> None:
    q = qs[i]
    rows = [[InlineKeyboardButton(text=o, callback_data=f"lia:{i}:{j}")] for j, o in enumerate(q["options"])]
    await message.answer(f"❓ <b>{i + 1}/{len(qs)}</b> {html.escape(q['q'])}",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(Listen.active, F.data.startswith("lia:"))
async def on_answer(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    _, i, j = cb.data.split(":")
    i, j = int(i), int(j)
    data = await state.get_data()
    if i != data["qi"]:
        return  # старая кнопка
    q = data["qs"][i]
    await cb.message.edit_reply_markup(reply_markup=None)
    ok = j == q["answer"]
    await cb.message.answer("✅ Верно!" if ok else f"❌ Правильно: <b>{html.escape(q['options'][q['answer']])}</b>")
    await track(repo, cb.message, cb.from_user.id, 2)
    correct, nxt = data["qc"] + ok, i + 1
    if nxt < len(data["qs"]):
        await state.update_data(qi=nxt, qc=correct)
        await ask(cb.message, data["qs"], nxt)
        return
    await state.clear()
    await cb.message.answer(f"🏁 Результат: {correct}/{len(data['qs'])}.\n\n"
                            f"📜 Текст истории:\n{html.escape(data['story'])}\n\n/listen — ещё одна история")
