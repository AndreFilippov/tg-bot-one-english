"""/progress — статистика обучения; /level — смена уровня: тест, выбор темы, переход на другой уровень."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import get_user
from services import clock, curriculum, progress

log = logging.getLogger(__name__)
router = Router()
PAGE = 8


class LevelTest(StatesGroup):
    answering = State()


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


@router.message(Command("progress"))
async def cmd_progress(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await state.clear()
    user = await get_user(repo, message.from_user, config)
    uid = user["user_id"]
    topics = curriculum.load_topics()
    tp = await repo.topic_progress(uid)
    done = sum(1 for t in topics if tp.get(t["id"], {}).get("status") == "done")
    number, total = curriculum.topic_number(user["current_topic"])
    topic = curriculum.topic_by_id(user["current_topic"])
    words = await repo.word_stats(uid)
    talks = await repo.session_stats(uid)
    days = await repo.activity_days(uid)
    today = clock.today_date()
    goal = user["daily_goal"] or 20
    today_points = days.get(today.isoformat(), {}).get("points", 0)
    week_points, week_lessons = progress.week_totals(days, today)
    n_streak = progress.streak(days, goal, today)

    scored = [(t, tp[t["id"]]) for t in topics if tp.get(t["id"], {}).get("total")]
    lines = [
        "📈 <b>Ваш прогресс</b>" + (f", {html.escape(user['nick'])}" if user.get("nick") else ""),
        f"Уровень: <b>{topic['level']}</b>",
        f"Тема сейчас: <b>{html.escape(topic['title'])}</b> ({number}/{total})",
        f"{progress.progress_bar(number - 1, total)} пройдено тем: {done}",
        "",
        f"🔥 Серия: <b>{n_streak}</b> дн. · Сегодня: {today_points}/{goal}",
        progress.week_bars(days, goal, today),
        f"За 7 дней: очков {week_points}, уроков {week_lessons}",
        "",
        f"📚 Слов: {words['total']} (выучено {words['learned']}, на повторение {words['due']})",
        f"🎙 Разговоров: {talks['talks']}, ваших реплик: {talks['turns']}",
        f"✏️ Исправлено ошибок за всё время: {await repo.mistake_count(uid)}",
    ]
    if scored:
        lines.append("\n<b>Точность по темам</b>")
        for t, row in scored[-6:]:
            share = round(100 * row["correct"] / row["total"])
            lines.append(f"{'✅' if share >= 80 else '⚠️'} {html.escape(t['title'])}: {share}% "
                         f"({row['correct']}/{row['total']})")
    usage = await repo.api_usage_today()
    if usage:
        lines.append("\n🤖 Запросов к Gemini сегодня: " + ", ".join(f"{m.replace('gemini-', '')}: {n}"
                                                                    for m, n in usage.items()))
    await message.answer("\n".join(lines))


# --- /level ---
def level_menu_kb(user: dict) -> InlineKeyboardMarkup:
    rows = [[btn("🧪 Пройти тест уровня заново", "lv:test")],
            [btn("📚 Выбрать тему вручную", "lp:0")]]
    first_a2 = next((t["id"] for t in curriculum.load_topics() if t["level"] == "A2"), None)
    if first_a2 and user["level"] != "A2":
        rows.append([btn("🎓 Перейти на уровень A2", f"lt:{first_a2}")])
    if user["level"] != "A1":
        rows.append([btn("↩️ Вернуться на уровень A1", f"lt:{curriculum.load_topics()[0]['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("level"))
async def cmd_level(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await state.clear()
    user = await get_user(repo, message.from_user, config)
    topic = curriculum.topic_by_id(user["current_topic"])
    await message.answer(f"🎚 <b>Уровень знаний</b>\nСейчас: {topic['level']}, тема «{html.escape(topic['title'])}».\n"
                         "Что хотите сделать?", reply_markup=level_menu_kb(user))


async def set_topic(user_id: int, repo: Repo, topic_id: str) -> dict:
    topic = curriculum.topic_by_id(topic_id)
    await repo.update_user(user_id, current_topic=topic["id"], level=topic["level"])
    return topic


@router.callback_query(F.data.startswith("lt:"))
async def on_pick_topic(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    await state.clear()
    topic = await set_topic(cb.from_user.id, repo, cb.data[3:])
    await cb.message.answer(f"✅ Теперь текущая тема: <b>{html.escape(topic['title'])}</b> ({topic['level']}).\n"
                            "/lesson — начать урок.")


@router.callback_query(F.data.startswith("lp:"))
async def on_topic_list(cb: CallbackQuery, repo: Repo) -> None:
    await cb.answer()
    page = int(cb.data[3:])
    topics = curriculum.load_topics()
    tp = await repo.topic_progress(cb.from_user.id)
    current = (await repo.get_or_create_user(cb.from_user.id))["current_topic"]
    chunk = topics[page * PAGE:(page + 1) * PAGE]
    rows = []
    for i, t in enumerate(chunk, page * PAGE + 1):
        icon = "▶️" if t["id"] == current else "✅" if tp.get(t["id"], {}).get("status") == "done" else "▫️"
        rows.append([btn(f"{icon} {i}. {t['title']}", f"lt:{t['id']}")])
    nav = []
    if page > 0:
        nav.append(btn("◀️", f"lp:{page - 1}"))
    if (page + 1) * PAGE < len(topics):
        nav.append(btn("▶️", f"lp:{page + 1}"))
    if nav:
        rows.append(nav)
    await cb.message.answer(f"📚 Выберите тему (страница {page + 1}/{(len(topics) - 1) // PAGE + 1}). "
                            "A1 — темы 1–33, дальше A2.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# --- повторный тест уровня (A1 + A2) ---
async def ask(message: Message, i: int) -> None:
    questions = curriculum.load_placement(include_a2=True)
    q = questions[i]
    rows = [[btn(o, f"lq:{i}:{j}")] for j, o in enumerate(q["options"])]
    await message.answer(f"❓ <b>{i + 1}/{len(questions)}</b>\n{q['q']}", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "lv:test")
async def on_start_test(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await state.set_state(LevelTest.answering)
    await state.update_data(first_fail=None)
    await cb.message.answer("Короткий тест из 10 вопросов: от простых к сложным. Выбирайте то, что кажется верным.")
    await ask(cb.message, 0)


@router.callback_query(LevelTest.answering, F.data.startswith("lq:"))
async def on_test_answer(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    _, i, j = cb.data.split(":")
    i, j = int(i), int(j)
    questions = curriculum.load_placement(include_a2=True)
    data = await state.get_data()
    await cb.message.edit_reply_markup(reply_markup=None)
    first_fail = data["first_fail"]
    if first_fail is None and j != questions[i]["answer"]:
        first_fail = questions[i]["topic"]
        await state.update_data(first_fail=first_fail)
    if i + 1 < len(questions):
        await ask(cb.message, i + 1)
        return
    await state.clear()
    topic = await set_topic(cb.from_user.id, repo, curriculum.start_topic_for(questions, first_fail))
    await cb.message.answer(f"✅ Тест пройден. Уровень: <b>{topic['level']}</b>, начинаем с темы "
                            f"«{html.escape(topic['title'])}».\n/lesson — начать урок.")
