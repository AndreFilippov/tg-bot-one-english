"""Еженедельная проверка по пройденным темам."""
import html
import logging
from collections import defaultdict
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, track
from services import curriculum
from services.exercises import check_translation
from services.gemini import GeminiService
from services.models import QuizSet
from services.prompts import render

log = logging.getLogger(__name__)
router = Router()

QUESTIONS = 8
TOPICS_IN_TEST = 5
PASS_RATIO = 0.8


class WeeklyTest(StatesGroup):
    answering = State()


def idk_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤷 Не знаю", callback_data="ts:idk")]])


def covered_topics(current: str) -> list[dict]:
    """Пройденные темы и текущая: последние TOPICS_IN_TEST по порядку программы."""
    topics = curriculum.load_topics()
    idx = next((i for i, t in enumerate(topics) if t["id"] == current), 0)
    return topics[max(0, idx + 1 - TOPICS_IN_TEST): idx + 1]


@router.message(Command("test"))
async def cmd_test(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    topics = covered_topics(user["current_topic"])
    since = f"Прошлая проверка: {user['last_test']}.\n" if user.get("last_test") else ""
    await message.answer(f"📝 <b>Проверка по пройденным темам</b>\n{since}Тем: {len(topics)}. ⏳ Готовлю вопросы…")
    try:
        prompt = render("test_generate", count=QUESTIONS,
                        topics="\n".join(f"{t['id']}: {t['title']} — {t['focus']}" for t in topics))
        test = await gemini.generate_json(QuizSet, prompt, await build_system(repo, user))
        valid = {t["id"] for t in topics}
        questions = [q.model_dump() for q in test.questions if q.topic_id in valid]
        if not questions:
            raise ValueError("no questions")
    except Exception as e:
        log.exception("test generation failed")
        await message.answer(error_text(e))
        return
    await state.set_state(WeeklyTest.answering)
    await state.update_data(tq=questions, ti=0, tright={}, ttotal={})
    await message.answer("Переводите на английский и отвечайте текстом. Подсказок в тесте нет.")
    await ask(message, questions, 0)


async def ask(message: Message, questions: list[dict], i: int) -> None:
    await message.answer(f"❓ <b>{i + 1}/{len(questions)}</b>\n<b>{html.escape(questions[i]['ru'])}</b>",
                         reply_markup=idk_kb())


async def process(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, user: dict,
                  answer: str) -> None:
    d = await state.get_data()
    q = d["tq"][d["ti"]]
    right, total = defaultdict(int, d["tright"]), defaultdict(int, d["ttotal"])
    ok = False
    if answer:
        try:
            title = curriculum.topic_by_id(q["topic_id"])["title"]
            check = await check_translation(gemini, await build_system(repo, user, q["topic_id"]), title,
                                            q["ru"], q["en"], answer)
        except Exception as e:
            log.exception("test check failed")
            await message.answer(error_text(e) + "\nОтправьте ответ ещё раз.")
            return
        ok = check.correct
        why = check.explanation
    else:
        why = ""
    total[q["topic_id"]] += 1
    await track(repo, message, user["user_id"], 1)
    if ok:
        right[q["topic_id"]] += 1
        await message.answer("✅ Верно!")
    else:
        await message.answer(f"❌ Правильно: <b>{html.escape(q['en'])}</b>" + (f"\n{html.escape(why)}" if why else ""))
        await repo.add_mistake(user["user_id"], answer or "(не знаю)", q["en"], why, type_=f"test:{q['topic_id']}")

    i = d["ti"] + 1
    if i < len(d["tq"]):
        await state.update_data(ti=i, tright=dict(right), ttotal=dict(total))
        await ask(message, d["tq"], i)
        return
    await finish(message, state, repo, user, right, total)


async def finish(message: Message, state: FSMContext, repo: Repo, user: dict, right: dict, total: dict) -> None:
    await state.clear()
    lines, weak = [], []
    for topic_id, n in total.items():
        await repo.add_topic_result(user["user_id"], topic_id, right.get(topic_id, 0), n)
        title = html.escape(curriculum.topic_by_id(topic_id)["title"])
        share = right.get(topic_id, 0) / n
        lines.append(f"{'✅' if share >= PASS_RATIO else '⚠️'} {title}: {right.get(topic_id, 0)}/{n}")
        if share < PASS_RATIO:
            weak.append(title)
    await repo.update_user(user["user_id"], last_test=date.today().isoformat())
    score, count = sum(right.values()), sum(total.values())
    text = f"🏁 <b>Результат: {score}/{count}</b>\n" + "\n".join(lines)
    if weak:
        text += "\n\nПовторите: " + ", ".join(weak) + ".\nМожно спросить /explain или пройти /lesson."
    else:
        text += "\n\nОтлично, все темы закреплены! 🎉"
    await message.answer(text)


@router.message(WeeklyTest.answering, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await process(message, state, repo, gemini, await get_user(repo, message.from_user, config), message.text)


@router.message(WeeklyTest.answering, F.voice)
async def on_voice(message: Message) -> None:
    await message.answer("В проверке ответ пишется текстом.")


@router.callback_query(WeeklyTest.answering, F.data == "ts:idk")
async def on_idk(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    await cb.answer()
    await process(cb.message, state, repo, gemini, await get_user(repo, cb.from_user, config), "")
