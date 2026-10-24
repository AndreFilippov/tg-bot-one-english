"""Профиль ученика: имя, город, занятие, цель, интересы, «что я помню». Мастер заполнения и /profile."""
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
from handlers.settings import time_kb
from services import curriculum, profile

log = logging.getLogger(__name__)
router = Router()

WIZARD = ["nick", "city", "occupation", "goal", "interests"]
PROMPTS = {
    "nick": "Как вас зовут? Так бот будет к вам обращаться.",
    "city": "В каком городе вы живёте?",
    "occupation": "Чем вы занимаетесь: работа или учёба? Например: «программист» или «студентка».",
    "goal": "Зачем вам английский?",
    "interests": "Что вам интересно? Отметьте кнопками (можно несколько) или напишите своё через запятую, "
                 "затем нажмите «Готово». Об этом мы будем разговаривать.",
}


class Profile(StatesGroup):
    text = State()      # ждём текст для поля pf_field
    interests = State() # выбор интересов
    fact = State()      # ручное добавление факта


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("⏭ Пропустить", "pf:skip")]])


def goal_kb() -> InlineKeyboardMarkup:
    rows = [[btn(g, f"pg:{i}")] for i, g in enumerate(profile.GOALS)]
    rows.append([btn("⏭ Пропустить", "pf:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interests_kb(selected: list[str]) -> InlineKeyboardMarkup:
    tags = curriculum.INTEREST_TAGS
    rows = []
    for i in range(0, len(tags), 2):
        rows.append([btn(("✅ " if t in selected else "") + t, f"pi:{j}") for j, t in enumerate(tags[i:i + 2], i)])
    rows.append([btn("✔️ Готово", "pi:ok")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_wizard(message: Message, state: FSMContext, onboarding: bool, fields: list[str] | None = None) -> None:
    await state.update_data(pf_queue=list(fields or WIZARD), pf_onboarding=onboarding)
    await next_step(message, state)


async def next_step(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    queue = data.get("pf_queue") or []
    if not queue:
        await finish_wizard(message, state, bool(data.get("pf_onboarding")))
        return
    field, rest = queue[0], queue[1:]
    await state.update_data(pf_queue=rest, pf_field=field)
    if field == "goal":
        await state.set_state(None)
        await message.answer(PROMPTS[field], reply_markup=goal_kb())
    elif field == "interests":
        await state.set_state(Profile.interests)
        selected = data.get("pf_tags")
        if selected is None:
            selected = []
            await state.update_data(pf_tags=selected)
        await message.answer(PROMPTS[field], reply_markup=interests_kb(selected))
    else:
        await state.set_state(Profile.text)
        await message.answer(PROMPTS[field], reply_markup=skip_kb())


async def finish_wizard(message: Message, state: FSMContext, onboarding: bool) -> None:
    await state.clear()
    if onboarding:
        await message.answer("Спасибо, я всё запомнил! 😊\n\nПоследний шаг — выберите время ежедневного напоминания:",
                             reply_markup=time_kb())
    else:
        await message.answer("✅ Профиль обновлён. /profile — посмотреть.")


@router.callback_query(F.data == "pf:skip")
async def on_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await next_step(cb.message, state)


@router.message(Profile.text, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    data = await state.get_data()
    field = data["pf_field"]
    await get_user(repo, message.from_user, config)
    await repo.update_user(message.from_user.id, **{field: message.text.strip()[:100]})
    await next_step(message, state)


@router.callback_query(F.data.startswith("pg:"))
async def on_goal(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await repo.update_user(cb.from_user.id, goal=profile.GOALS[int(cb.data[3:])])
    await next_step(cb.message, state)


@router.callback_query(Profile.interests, F.data.startswith("pi:"))
async def on_interest(cb: CallbackQuery, state: FSMContext, repo: Repo, config: Config) -> None:
    await cb.answer()
    data = await state.get_data()
    selected: list[str] = list(data.get("pf_tags") or [])
    if cb.data == "pi:ok":
        await cb.message.edit_reply_markup(reply_markup=None)
        await repo.update_user(cb.from_user.id, interests=", ".join(selected))
        await state.update_data(pf_tags=None)
        await next_step(cb.message, state)
        return
    tag = curriculum.INTEREST_TAGS[int(cb.data[3:])]
    selected = [t for t in selected if t != tag] if tag in selected else selected + [tag]
    await state.update_data(pf_tags=selected)
    await cb.message.edit_reply_markup(reply_markup=interests_kb(selected))


@router.message(Profile.interests, F.text & ~F.text.startswith("/"))
async def on_interest_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = list(data.get("pf_tags") or [])
    for tag in message.text.split(","):
        tag = tag.strip()[:40]
        if tag and tag not in selected:
            selected.append(tag)
    await state.update_data(pf_tags=selected)
    await message.answer(f"Добавил. Сейчас выбрано: {html.escape(', '.join(selected))}.\n"
                         "Выберите ещё или нажмите «Готово».", reply_markup=interests_kb(selected))


# --- /profile ---
def profile_kb(count_facts: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("✏️ Имя", "pe:nick"), btn("🏙 Город", "pe:city"), btn("💼 Занятие", "pe:occupation")],
        [btn("🎯 Цель", "pe:goal"), btn("⭐ Интересы", "pe:interests")],
        [btn(f"🧠 Что я помню ({count_facts})", "pe:facts")],
    ])


async def show_profile(message: Message, user: dict) -> None:
    facts = profile.facts_of(user)
    await message.answer(f"👤 <b>Ваш профиль</b>\n{html.escape(profile.profile_for_user(user))}\n\n"
                         "Бот учитывает это в разговорах и уроках и больше не переспрашивает.",
                         reply_markup=profile_kb(len(facts)))


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await state.clear()
    await show_profile(message, await get_user(repo, message.from_user, config))


@router.callback_query(F.data.startswith("pe:"))
async def on_edit(cb: CallbackQuery, state: FSMContext, repo: Repo, config: Config) -> None:
    await cb.answer()
    field = cb.data[3:]
    if field == "facts":
        await show_facts(cb.message, await get_user(repo, cb.from_user, config))
        return
    await state.clear()
    if field == "interests":
        user = await get_user(repo, cb.from_user, config)
        await state.update_data(pf_tags=profile.interests_of(user))
    await start_wizard(cb.message, state, onboarding=False, fields=[field])


# --- факты («что я помню») ---
async def show_facts(message: Message, user: dict) -> None:
    facts = profile.facts_of(user)
    rows = [[btn(f"🗑 {f[:40]}", f"pd:{i}")] for i, f in enumerate(facts)]
    rows.append([btn("➕ Добавить факт", "pa:fact")])
    text = "🧠 <b>Что я о вас помню</b>\n" + ("\n".join(f"{i + 1}. {html.escape(f)}" for i, f in enumerate(facts))
                                              or "Пока ничего. Факты появятся после разговоров.")
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("pd:"))
async def on_delete_fact(cb: CallbackQuery, repo: Repo, config: Config) -> None:
    await cb.answer("Удалено")
    await repo.remove_fact(cb.from_user.id, int(cb.data[3:]))
    await show_facts(cb.message, await get_user(repo, cb.from_user, config))


@router.callback_query(F.data == "pa:fact")
async def on_add_fact(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(Profile.fact)
    await cb.message.answer("Напишите факт о себе по-английски или по-русски, например: "
                            "<i>У меня есть кошка Том</i>.")


@router.message(Profile.fact, F.text & ~F.text.startswith("/"))
async def on_fact_text(message: Message, state: FSMContext, repo: Repo) -> None:
    await repo.add_fact(message.from_user.id, message.text.strip()[:200])
    await state.clear()
    await message.answer("✅ Запомнил.")


# --- факты, предложенные ботом после разговора ---
@router.callback_query(F.data.startswith(("fk:", "fx:")))
async def on_suggested_fact(cb: CallbackQuery, repo: Repo) -> None:
    await cb.answer()
    kind, fact_id = cb.data.split(":")
    text = await repo.pop_pending_fact(int(fact_id), cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=None)
    if text and kind == "fk":
        await repo.add_fact(cb.from_user.id, text)
        await cb.message.answer(f"💾 Запомнил: {html.escape(text)}")
