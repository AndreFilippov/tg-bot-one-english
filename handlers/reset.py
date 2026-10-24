"""/reset — сброс данных с подтверждением кнопкой."""
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db.repo import Repo
from services.scheduler import Reminders

log = logging.getLogger(__name__)
router = Router()

OPTIONS = {
    "words": ("🔤 Словарь", "все слова и расписание их повторения"),
    "progress": ("📈 Прогресс", "пройденные темы, ошибки, историю разговоров, серию и возврат на тему 1"),
    "profile": ("👤 Профиль", "имя, интересы и всё, что бот о вас помнит"),
    "all": ("💣 Всё", "вообще всё; бот начнёт знакомство заново"),
}


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = [[btn(label, f"rs:{key}")] for key, (label, _) in OPTIONS.items()]
    await message.answer("🧹 <b>Что сбросить?</b> Настройки (голос, скорость) сохранятся, кроме варианта «Всё».",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("rs:"))
async def on_choose(cb: CallbackQuery) -> None:
    await cb.answer()
    key = cb.data[3:]
    if key not in OPTIONS:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer("Ок, ничего не сбрасываю.")
        return
    label, what = OPTIONS[key]
    await cb.message.answer(f"⚠️ Сбросить: <b>{label}</b>?\nБудет удалено: {what}. Это нельзя отменить.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                btn("Да, сбросить", f"rc:{key}"), btn("Отмена", "rs:no")]]))


@router.callback_query(F.data.startswith("rc:"))
async def on_confirm(cb: CallbackQuery, state: FSMContext, repo: Repo, reminders: Reminders) -> None:
    await cb.answer()
    key = cb.data[3:]
    if key not in OPTIONS:
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await repo.reset(cb.from_user.id, key)
    if key == "all":
        reminders.schedule(cb.from_user.id, None)
        await cb.message.answer("🧽 Всё сброшено. /start — начать знакомство заново.")
    else:
        await cb.message.answer(f"✅ Сброшено: {OPTIONS[key][0]}.")
    log.info("reset %s for user %s", key, cb.from_user.id)
