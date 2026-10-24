import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, say
from services import curriculum
from services.audio import download_voice
from services.gemini import GeminiService
from services.models import TalkSummary, TalkTurn
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()

SLOW_RATE = -30
MAX_HISTORY = 20


class Talk(StatesGroup):
    choosing = State()
    active = State()


def scenarios_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in curriculum.load_scenarios().values():
        kb.button(text=f"{s['emoji']} {s['title']}", callback_data=f"sc:{s['id']}")
    kb.adjust(2)
    return kb.as_markup()


def turn_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐢 Медленнее", callback_data="t:slow"),
         InlineKeyboardButton(text="🇷🇺 Перевод", callback_data="t:tr")],
        [InlineKeyboardButton(text="💡 Подсказка", callback_data="t:hint"),
         InlineKeyboardButton(text="⏹ Завершить", callback_data="t:end")],
    ])


def format_history(history: list[list[str]]) -> str:
    return "\n".join(f"{who}: {text}" for who, text in history[-10:]) or "(empty)"


async def begin_talk(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                     user: dict, scenario: dict, *, topic_id: str | None = None, extra: dict | None = None,
                     max_turns: int = 0) -> None:
    """Запускает голосовой диалог. extra — данные потока (например, урока), они переживут диалог."""
    await message.answer(f"{scenario['emoji']} <b>{scenario['title']}</b>\n"
                         "Слушайте и отвечайте голосовым (можно и текстом). Я начинаю…")
    try:
        system = await build_system(repo, user, topic_id)
        opening = await gemini.generate_text(render("talk_opening", scenario=scenario["goal"]), system)
        session_id = await repo.start_session(user["user_id"], "talk", scenario["id"])
        await state.set_state(Talk.active)
        await state.update_data(session_id=session_id, goal=scenario["goal"], topic_id=topic_id,
                                history=[["Partner", opening]], last_reply=opening, turns=0, mistakes=[],
                                new_words=[], max_turns=max_turns, flow=extra or {}, aux={})
        await say(message, tts, user, opening, markup=turn_kb())
    except Exception as e:
        log.exception("start talk failed")
        await state.clear()
        await message.answer(error_text(e))


@router.message(Command("talk"))
async def cmd_talk(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await get_user(repo, message.from_user, config)
    await state.clear()
    await state.set_state(Talk.choosing)
    await message.answer("🎙 Выберите тему разговора:", reply_markup=scenarios_kb())


@router.callback_query(F.data.startswith("sc:"))
async def pick_scenario(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService,
                        tts: TTSService, config: Config) -> None:
    await cb.answer()
    scenario = curriculum.load_scenarios().get(cb.data[3:])
    if not scenario:
        return
    user = await get_user(repo, cb.from_user, config)
    await cb.message.edit_reply_markup(reply_markup=None)
    await begin_talk(cb.message, state, repo, gemini, tts, user, scenario)


async def handle_answer(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService,
                        tts: TTSService, config: Config, audio: bytes | None, text: str | None) -> None:
    data = await state.get_data()
    user = await get_user(repo, message.from_user, config)
    try:
        if audio is not None:
            input_description = "The student's answer is in the attached audio message. Transcribe it first."
        else:
            input_description = f'The student answered in text: "{text}"'
        prompt = render("talk_turn", scenario=data["goal"], history=format_history(data["history"]),
                        last_reply=data["last_reply"], input_description=input_description)
        turn = await gemini.generate_json(TalkTurn, prompt, await build_system(repo, user, data["topic_id"]),
                                          audio=audio)
    except Exception as e:
        log.exception("talk turn failed")
        await message.answer(error_text(e))
        return

    if not turn.recognized or not (turn.transcript.strip() or text):
        await message.answer("🙉 Я не расслышал(а). Скажите ещё раз, пожалуйста — чётко и не спеша.")
        return

    heard = turn.transcript.strip() or text
    lines = [f"🗣 Вы сказали: <i>{html.escape(heard)}</i>"]
    if turn.corrections:
        lines.append("\n✏️ <b>Исправления:</b>")
        for c in turn.corrections:
            lines.append(f"❌ {html.escape(c.wrong)} → ✅ <b>{html.escape(c.right)}</b>\n"
                         f"   {html.escape(c.explanation)}")
    elif turn.is_correct:
        lines.append("✅ Всё правильно!")
    if turn.pronunciation_notes.strip():
        lines.append(f"\n🔊 <b>Произношение:</b> {html.escape(turn.pronunciation_notes)}")
    await message.answer("\n".join(lines))

    for c in turn.corrections:
        await repo.add_mistake(user["user_id"], c.wrong, c.right, c.explanation, data["session_id"])
    history = (data["history"] + [["Student", heard], ["Partner", turn.reply]])[-MAX_HISTORY:]
    turns = data["turns"] + 1
    mistakes = data["mistakes"] + [f"{c.wrong} -> {c.right} ({c.explanation})" for c in turn.corrections]
    new_words = data["new_words"] + [w.model_dump() for w in turn.new_words]
    await state.update_data(history=history, last_reply=turn.reply, turns=turns,
                            mistakes=mistakes, new_words=new_words)
    await repo.save_session_progress(data["session_id"], turns, history)

    last_turn = bool(data["max_turns"]) and turns >= data["max_turns"]
    try:
        await say(message, tts, user, turn.reply, markup=None if last_turn else turn_kb())
    except Exception as e:
        log.exception("tts failed")
        await message.answer(f"{error_text(e)}\n\n{html.escape(turn.reply)}",
                             reply_markup=None if last_turn else turn_kb())
    if last_turn:
        await message.answer("🏁 Мини-диалог закончен, подводим итоги.")
        await finish_talk(message, state, repo, gemini, user)


@router.message(Talk.active, F.voice)
async def on_voice(message: Message, bot: Bot, state: FSMContext, repo: Repo, gemini: GeminiService,
                   tts: TTSService, config: Config) -> None:
    try:
        audio = await download_voice(bot, message.voice.file_id)
    except Exception:
        log.exception("voice download failed")
        await message.answer("😕 Не удалось скачать голосовое. Попробуйте ещё раз.")
        return
    await handle_answer(message, state, repo, gemini, tts, config, audio=audio, text=None)


@router.message(Talk.active, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService,
                  tts: TTSService, config: Config) -> None:
    await handle_answer(message, state, repo, gemini, tts, config, audio=None, text=message.text)


@router.callback_query(Talk.active, F.data == "t:slow")
async def on_slow(cb: CallbackQuery, state: FSMContext, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    data = await state.get_data()
    user = await get_user(repo, cb.from_user, config)
    try:
        await say(cb.message, tts, user, data["last_reply"], rate=SLOW_RATE, caption_prefix="🐢 ",
                  markup=turn_kb())
    except Exception as e:
        log.exception("slow tts failed")
        await cb.message.answer(error_text(e))


@router.callback_query(Talk.active, F.data.in_({"t:tr", "t:hint"}))
async def on_tr_hint(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService,
                     config: Config) -> None:
    await cb.answer()
    data = await state.get_data()
    kind = "tr" if cb.data == "t:tr" else "hint"
    cache = data.get("aux", {})
    key = f"{kind}:{data['last_reply']}"
    try:
        if key not in cache:
            user = await get_user(repo, cb.from_user, config)
            name = "talk_translate" if kind == "tr" else "talk_hint"
            cache[key] = await gemini.generate_text(
                render(name, text=data["last_reply"], scenario=data["goal"]),
                await build_system(repo, user, data["topic_id"]))
            await state.update_data(aux=cache)
    except Exception as e:
        log.exception("aux request failed")
        await cb.message.answer(error_text(e))
        return
    title = "🇷🇺 Перевод" if kind == "tr" else "💡 Подсказка"
    await cb.message.answer(f"{title}:\n{html.escape(cache[key])}")


@router.callback_query(Talk.active, F.data == "t:end")
async def on_end(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await finish_talk(cb.message, state, repo, gemini, user)


async def finish_talk(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, user: dict) -> None:
    """Итог диалога: ошибки, правила, новые слова (они попадают в SRS). Затем продолжает поток урока."""
    data = await state.get_data()
    flow = data.get("flow") or {}
    if data["turns"] == 0:
        await repo.finish_session(data["session_id"], None)
        await state.clear()
        await message.answer("Разговор завершён без ответов. /talk — попробовать снова.")
        if flow.get("lesson"):
            from handlers import lesson
            await lesson.finish_lesson(message, repo, user, flow["lesson"])
        return
    await message.answer("⏳ Подвожу итоги…")
    try:
        prompt = render("talk_summary", scenario=data["goal"], history=format_history(data["history"]),
                        mistakes_list="\n".join(data["mistakes"]) or "none")
        summary = await gemini.generate_json(TalkSummary, prompt, await build_system(repo, user, data["topic_id"]))
    except Exception as e:
        log.exception("summary failed")
        await message.answer(error_text(e) + "\nНажмите «⏹ Завершить» ещё раз.")
        return

    # новые слова: из реплик диалога и из итога, без дублей
    seen: set[str] = set()
    added: list[str] = []
    for w in [*data["new_words"], *[x.model_dump() for x in summary.new_words]]:
        key = w["word"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            if await repo.add_word(user["user_id"], w["word"], w["translation"], w.get("example", "")):
                added.append(f"<b>{html.escape(w['word'])}</b> — {html.escape(w['translation'])}")

    parts = [f"🏁 <b>Итоги разговора</b>\nРеплик с вашей стороны: {data['turns']}"]
    if summary.main_mistakes:
        parts.append("❗ <b>Главные ошибки:</b>\n" + "\n".join(f"• {html.escape(m)}" for m in summary.main_mistakes))
    if summary.rules:
        parts.append("📘 <b>Повторите:</b>\n" + "\n".join(f"• {html.escape(r)}" for r in summary.rules))
    if added:
        parts.append("🆕 <b>Новые слова (добавлены в словарь):</b>\n" + "\n".join(f"• {a}" for a in added))
    if summary.comment:
        parts.append(html.escape(summary.comment))
    if not flow.get("lesson"):
        parts.append("/talk — ещё один разговор")
    await repo.finish_session(data["session_id"], summary.model_dump())
    await state.clear()
    await message.answer("\n\n".join(parts))
    if flow.get("lesson"):
        from handlers import lesson
        await lesson.finish_lesson(message, repo, user, flow["lesson"])
