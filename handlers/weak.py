"""/weak — самые частые ошибки и тренировка на них."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, track
from services.exercises import check_translation
from services.gemini import GeminiService
from services.models import PracticeSet
from services.prompts import render

log = logging.getLogger(__name__)
router = Router()


class Weak(StatesGroup):
    answering = State()


def idk_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤷 Не знаю", callback_data="wk:idk")]])


@router.message(Command("weak"))
async def cmd_weak(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await state.clear()
    user = await get_user(repo, message.from_user, config)
    top = await repo.top_mistakes(user["user_id"], 5)
    if not top:
        await message.answer("Пока нет накопленных ошибок. Поговорите в /talk или пройдите /lesson, и я соберу ваши слабые места.")
        return
    lines = ["🎯 <b>Ваши частые ошибки</b>"]
    for m in top:
        times = f" ×{m['n']}" if m["n"] > 1 else ""
        lines.append(f"❌ {html.escape(m['wrong'])} → ✅ <b>{html.escape(m['right'])}</b>{times}")
        if m["explanation"]:
            lines.append(f"   {html.escape(m['explanation'])}")
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏋️ Потренировать (5 фраз)", callback_data="wk:start")]]))


@router.callback_query(F.data == "wk:start")
async def on_start(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    top = await repo.top_mistakes(user["user_id"], 6)
    if not top:
        await cb.message.answer("Ошибок пока нет.")
        return
    await cb.message.answer("⏳ Готовлю упражнения на ваши ошибки…")
    try:
        mistakes = "\n".join(f"{m['wrong']} -> {m['right']} ({m['n']}x)" for m in top)
        practice = await gemini.generate_json(PracticeSet, render("weak_practice", mistakes=mistakes),
                                              await build_system(repo, user))
        exercises = [e.model_dump() for e in practice.exercises[:5]]
        if not exercises:
            raise ValueError("no exercises")
    except Exception as e:
        log.exception("weak practice failed")
        await cb.message.answer(error_text(e))
        return
    await state.clear()
    await state.set_state(Weak.answering)
    await state.update_data(wk=exercises, wi=0, wc=0)
    await ask(cb.message, exercises, 0)


async def ask(message: Message, exercises: list[dict], i: int) -> None:
    await message.answer(f"✍️ <b>{i + 1}/{len(exercises)}</b> Переведите:\n<b>{html.escape(exercises[i]['ru'])}</b>",
                         reply_markup=idk_kb())


async def process(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, user: dict,
                  answer: str) -> None:
    d = await state.get_data()
    ex = d["wk"][d["wi"]]
    ok, why = False, ""
    if answer:
        try:
            check = await check_translation(gemini, await build_system(repo, user), "weak spots", ex["ru"], ex["en"],
                                            answer)
        except Exception as e:
            log.exception("weak check failed")
            await message.answer(error_text(e) + "\nОтправьте ответ ещё раз.")
            return
        ok, why = check.correct, check.explanation
    await track(repo, message, user["user_id"], 1)
    if ok:
        await message.answer("✅ Верно!")
    else:
        await message.answer(f"❌ Правильно: <b>{html.escape(ex['en'])}</b>" + (f"\n{html.escape(why)}" if why else ""))
        await repo.add_mistake(user["user_id"], answer or "(не знаю)", ex["en"], why, type_="weak")
    correct, i = d["wc"] + ok, d["wi"] + 1
    if i < len(d["wk"]):
        await state.update_data(wi=i, wc=correct)
        await ask(message, d["wk"], i)
        return
    await state.clear()
    verdict = "Отлично! 🎉" if correct == len(d["wk"]) else "Повторите ещё раз позже: /weak"
    await message.answer(f"🏁 Результат: {correct}/{len(d['wk'])}. {verdict}")


@router.message(Weak.answering, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await process(message, state, repo, gemini, await get_user(repo, message.from_user, config), message.text)


@router.callback_query(Weak.answering, F.data == "wk:idk")
async def on_idk(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await cb.answer()
    await process(cb.message, state, repo, gemini, await get_user(repo, cb.from_user, config), "")
