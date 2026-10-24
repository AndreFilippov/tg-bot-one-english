from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers import profile
from handlers.helpers import get_user
from services import curriculum

router = Router()

HELP = ("🎙 /talk — голосовой разговор\n📚 /lesson — урок на сегодня\n💬 /chat — переписка\n"
        "🎤 /repeat — повтори за мной (произношение)\n🎧 /listen — аудирование\n"
        "🔄 /translate — переводчик (текст и голос)\n❓ /explain — объяснить правило\n"
        "🔤 /words — словарь и повторение (/add, /due, /export, /import)\n🎯 /weak — мои слабые места\n"
        "📝 /test — проверка\n📈 /progress — прогресс\n🎚 /level — сменить уровень или тему\n"
        "👤 /profile — что бот помнит обо мне\n⚙️ /settings — настройки\n🧹 /reset — сброс данных\n"
        "⏹ /cancel — выйти из режима")


class Onboarding(StatesGroup):
    test = State()


def question_kb(i: int, options: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=o, callback_data=f"pt:{i}:{j}")] for j, o in enumerate(options)])


async def ask(message: Message, i: int) -> None:
    questions = curriculum.load_placement()
    q = questions[i]
    await message.answer(f"❓ <b>{i + 1}/{len(questions)}</b>\n{q['q']}", reply_markup=question_kb(i, q["options"]))


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repo, config: Config, state: FSMContext) -> None:
    await state.clear()
    user = await get_user(repo, message.from_user, config)
    if user["onboarded"]:
        await message.answer(f"С возвращением! 👋\n\n{HELP}")
        return
    await message.answer(
        "👋 Привет! Я помогу выучить американский английский с нуля.\n\n"
        "Главное — голосовой разговор: я говорю по-английски, вы отвечаете голосовым, а я мягко исправляю ошибки.\n\n"
        f"Сначала короткий тест из {len(curriculum.load_placement())} вопросов, чтобы понять, с какой темы начать. "
        "Не бойтесь ошибиться — выбирайте то, что кажется верным.")
    await state.set_state(Onboarding.test)
    await state.update_data(first_fail=None)
    await ask(message, 0)


@router.callback_query(Onboarding.test, F.data.startswith("pt:"))
async def on_answer(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    _, i, j = cb.data.split(":")
    i, j = int(i), int(j)
    questions = curriculum.load_placement()
    data = await state.get_data()
    await cb.message.edit_reply_markup(reply_markup=None)
    first_fail = data["first_fail"]
    if first_fail is None and j != questions[i]["answer"]:
        first_fail = questions[i]["topic"]
        await state.update_data(first_fail=first_fail)
    if i + 1 < len(questions):
        await ask(cb.message, i + 1)
        return

    start_topic = curriculum.start_topic_for(questions, first_fail)
    await state.clear()
    topic = curriculum.topic_by_id(start_topic)
    await repo.update_user(cb.from_user.id, current_topic=start_topic, level=topic["level"])
    await cb.message.answer(f"✅ Тест пройден! Начнём с темы: <b>{topic['title']}</b>.\n\n"
                            "Теперь расскажите немного о себе: так я буду общаться интереснее и не стану переспрашивать "
                            "одно и то же. Любой шаг можно пропустить.")
    await profile.start_wizard(cb.message, state, onboarding=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок, вышли из режима.\n\n" + HELP)
