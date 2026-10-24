import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import error_text, get_user, say
from services.scheduler import Reminders, parse_hhmm
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()

VOICES = {
    "en-US-AriaNeural": "Aria (жен.)", "en-US-JennyNeural": "Jenny (жен.)", "en-US-AvaNeural": "Ava (жен.)",
    "en-US-GuyNeural": "Guy (муж.)", "en-US-AndrewNeural": "Andrew (муж.)",
    "en-US-ChristopherNeural": "Christopher (муж.)",
}
RATES = [-40, -30, -20, -10, 0]
TIMES = ["08:00", "12:00", "18:00", "20:00", "21:00"]


class Settings(StatesGroup):
    waiting_time = State()


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def menu(user: dict) -> tuple[str, InlineKeyboardMarkup]:
    text = ("⚙️ <b>Настройки</b>\n"
            f"Голос: {VOICES.get(user['voice'], user['voice'])}\n"
            f"Скорость речи: {user['speech_rate']:+d}%\n"
            f"Текст под спойлером: {'да' if user['show_text'] else 'нет'}\n"
            f"Напоминание: {user['reminder_time'] or 'выключено'}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("🗣 Голос", "st:voice"), btn("🐢 Скорость", "st:rate")],
        [btn(f"👁 Показывать текст: {'да' if user['show_text'] else 'нет'}", "st:text")],
        [btn("⏰ Время напоминания", "st:time")],
    ])
    return text, kb


def time_kb() -> InlineKeyboardMarkup:
    rows = [[btn(t, f"st:t:{t}") for t in TIMES],
            [btn("✍️ Другое время", "st:t:custom"), btn("🔕 Выключить", "st:t:off")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def edit_or_answer(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:  # «message is not modified» и т. п.
        await cb.message.answer(text, reply_markup=kb)


async def show_menu(cb: CallbackQuery, repo: Repo, config: Config) -> None:
    text, kb = menu(await get_user(repo, cb.from_user, config))
    await edit_or_answer(cb, text, kb)


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await state.clear()
    text, kb = menu(await get_user(repo, message.from_user, config))
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "st:menu")
async def on_menu(cb: CallbackQuery, repo: Repo, config: Config) -> None:
    await cb.answer()
    await show_menu(cb, repo, config)


@router.callback_query(F.data == "st:voice")
async def on_voice_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = [[btn(name, f"st:v:{i}")] for i, name in enumerate(VOICES.values())]
    await edit_or_answer(cb, "🗣 Выберите голос (американский английский):", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("st:v:"))
async def on_voice_pick(cb: CallbackQuery, repo: Repo, tts: TTSService, config: Config) -> None:
    await cb.answer()
    voice = list(VOICES)[int(cb.data[5:])]
    await repo.update_user(cb.from_user.id, voice=voice)
    user = await get_user(repo, cb.from_user, config)
    try:
        await say(cb.message, tts, user, "Hi! This is my voice. Let's learn English together.", show_text=False)
    except Exception as e:
        log.exception("sample tts failed")
        await cb.message.answer(error_text(e))
    await show_menu(cb, repo, config)


@router.callback_query(F.data == "st:rate")
async def on_rate_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = [[btn(f"{r:+d}%" if r else "обычная (0%)", f"st:r:{r}") for r in RATES[:3]],
            [btn(f"{r:+d}%" if r else "обычная (0%)", f"st:r:{r}") for r in RATES[3:]]]
    await edit_or_answer(cb, "🐢 Скорость речи (чем меньше число, тем медленнее):", InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("st:r:"))
async def on_rate_pick(cb: CallbackQuery, repo: Repo, config: Config) -> None:
    await cb.answer()
    await repo.update_user(cb.from_user.id, speech_rate=int(cb.data[5:]))
    await show_menu(cb, repo, config)


@router.callback_query(F.data == "st:text")
async def on_toggle_text(cb: CallbackQuery, repo: Repo, config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await repo.update_user(cb.from_user.id, show_text=0 if user["show_text"] else 1)
    await show_menu(cb, repo, config)


@router.callback_query(F.data == "st:time")
async def on_time_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    await edit_or_answer(cb, "⏰ Когда напоминать об уроке? (Часовой пояс задаётся в .env: TIMEZONE)", time_kb())


async def save_time(message: Message, repo: Repo, reminders: Reminders, user_id: int, hhmm: str | None) -> None:
    user = await repo.get_or_create_user(user_id)
    await repo.update_user(user_id, reminder_time=hhmm)
    reminders.schedule(user_id, hhmm)
    when = f"Буду напоминать каждый день в {hhmm}." if hhmm else "Напоминания выключены."
    if not user["onboarded"]:
        await repo.update_user(user_id, onboarded=1)
        await message.answer(f"{when}\n\n🎉 Всё готово! Начните с /lesson или поговорите голосом: /talk.\n"
                             "Остальные команды: /chat /explain /words /test /settings")
    else:
        await message.answer(when)


@router.callback_query(F.data.startswith("st:t:"))
async def on_time_pick(cb: CallbackQuery, state: FSMContext, repo: Repo, reminders: Reminders) -> None:
    await cb.answer()
    value = cb.data[5:]
    if value == "custom":
        await state.set_state(Settings.waiting_time)
        await cb.message.answer("Напишите время в формате ЧЧ:ММ, например <code>19:30</code>.")
        return
    await save_time(cb.message, repo, reminders, cb.from_user.id, None if value == "off" else value)


@router.message(Settings.waiting_time, F.text & ~F.text.startswith("/"))
async def on_custom_time(message: Message, state: FSMContext, repo: Repo, reminders: Reminders) -> None:
    hhmm = parse_hhmm(message.text)
    if not hhmm:
        await message.answer("Не понял время. Формат ЧЧ:ММ, например <code>19:30</code>.")
        return
    await state.clear()
    await save_time(message, repo, reminders, message.from_user.id, hhmm)
