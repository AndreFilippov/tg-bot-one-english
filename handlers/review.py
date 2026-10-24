"""Интервальное повторение слов (SRS): русское слово -> ответ текстом или голосом."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import error_text, get_user, say, track
from services import srs, text_match
from services.audio import download_voice
from services.gemini import GeminiService
from services.models import Transcript
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()


class Review(StatesGroup):
    answering = State()


def card_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🤷 Не знаю", callback_data="rv:skip"),
        InlineKeyboardButton(text="⏹ Выйти", callback_data="rv:stop"),
    ]])


def grade(answer: str, expected: str) -> tuple[int, str]:
    """Оценка SM-2 (0..5) и вердикт."""
    if text_match.is_exact(answer, expected):
        return 5, "✅ Верно!"
    if text_match.is_close(answer, expected):
        return 4, "👌 Почти — небольшая опечатка."
    return 1, "❌ Не совсем."


async def start_review(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                       user: dict, *, flow: dict | None = None, limit: int = 20) -> None:
    ids = await repo.due_word_ids(user["user_id"], limit)
    if not ids:
        await message.answer("🎉 Сейчас нет слов на повторение.")
        await review_done(message, state, repo, gemini, tts, user, flow or {}, {"good": 0, "bad": 0}, silent=True)
        return
    await state.set_state(Review.answering)
    await state.update_data(rv_ids=ids, rv_idx=0, rv_requeued=[], rv_good=0, rv_bad=0, flow=flow or {})
    await message.answer(f"🔁 <b>Повторение слов</b>: {len(ids)}. Отвечайте текстом или голосовым.")
    await show_card(message, repo, ids[0], 1, len(ids))


async def show_card(message: Message, repo: Repo, word_id: int, number: int, total: int) -> None:
    word = await repo.get_word(word_id)
    await message.answer(f"🔤 <b>{number}/{total}</b>. Как по-английски:\n<b>{html.escape(word['translation'])}</b>",
                         reply_markup=card_kb())


async def review_done(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                      user: dict, flow: dict, stats: dict, silent: bool = False) -> None:
    await state.clear()
    if not silent:
        await message.answer(f"🏁 Повторение закончено. Верно: {stats['good']}, нужно подучить: {stats['bad']}.")
    if flow.get("lesson"):
        from handlers import lesson
        await lesson.step_grammar(message, state, repo, gemini, tts, user, flow["lesson"])


async def process_answer(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                         user: dict, answer: str) -> None:
    data = await state.get_data()
    ids, idx = data["rv_ids"], data["rv_idx"]
    word = await repo.get_word(ids[idx])
    quality, verdict = grade(answer, word["word"]) if answer else (1, "🤷 Ничего страшного.")
    new = srs.review(word["ease"], word["interval"], word["reps"], quality)
    await repo.update_word_srs(word["id"], new.ease, new.interval, new.reps, new.due)
    await track(repo, message, user["user_id"], 1)

    lines = [verdict, f"Правильно: <b>{html.escape(word['word'])}</b> — {html.escape(word['translation'])}"]
    if word["example"]:
        lines.append(f"<i>{html.escape(word['example'])}</i>")
    lines.append(f"Следующее повторение через {new.interval} дн.")
    try:
        await say(message, tts, user, word["word"], show_text=False, caption_prefix="\n".join(lines))
    except Exception:
        log.exception("word tts failed")
        await message.answer("\n".join(lines))

    good, bad = data["rv_good"] + (quality >= 3), data["rv_bad"] + (quality < 3)
    requeued = data["rv_requeued"]
    if quality < 3 and word["id"] not in requeued:  # провалившееся слово спрашиваем ещё раз в конце
        ids = ids + [word["id"]]
        requeued = requeued + [word["id"]]
    idx += 1
    if idx >= len(ids):
        await review_done(message, state, repo, gemini, tts, user, data["flow"], {"good": good, "bad": bad})
        return
    await state.update_data(rv_ids=ids, rv_idx=idx, rv_requeued=requeued, rv_good=good, rv_bad=bad)
    await show_card(message, repo, ids[idx], idx + 1, len(ids))


@router.message(Review.answering, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                  config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await process_answer(message, state, repo, gemini, tts, user, message.text)


@router.message(Review.answering, F.voice)
async def on_voice(message: Message, bot: Bot, state: FSMContext, repo: Repo, gemini: GeminiService,
                   tts: TTSService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    try:
        audio = await download_voice(bot, message.voice.file_id)
        result = await gemini.generate_json(Transcript, render("voice_transcribe"),
                                            "You are an accurate speech transcriber.", audio=audio)
    except Exception as e:
        log.exception("voice answer failed")
        await message.answer(error_text(e))
        return
    if not result.recognized or not result.transcript.strip():
        await message.answer("🙉 Не расслышал(а). Повторите, пожалуйста.")
        return
    await message.answer(f"🗣 Вы сказали: <i>{html.escape(result.transcript)}</i>")
    await process_answer(message, state, repo, gemini, tts, user, result.transcript)


@router.callback_query(Review.answering, F.data == "rv:skip")
async def on_skip(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                  config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await process_answer(cb.message, state, repo, gemini, tts, user, "")


@router.callback_query(Review.answering, F.data == "rv:stop")
async def on_stop(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                  config: Config) -> None:
    await cb.answer()
    data = await state.get_data()
    user = await get_user(repo, cb.from_user, config)
    await review_done(cb.message, state, repo, gemini, tts, user, data["flow"],
                      {"good": data["rv_good"], "bad": data["rv_bad"]})
