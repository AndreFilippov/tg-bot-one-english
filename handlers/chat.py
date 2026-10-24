"""Текстовая переписка на простом английском; исправления — в конце сообщения бота."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user
from services.gemini import GeminiService
from services.models import ChatTurn
from services.prompts import render

log = logging.getLogger(__name__)
router = Router()
MAX_HISTORY = 12


class Chat(StatesGroup):
    active = State()


@router.message(Command("chat"))
async def cmd_chat(message: Message, state: FSMContext, repo: Repo, config: Config) -> None:
    await get_user(repo, message.from_user, config)
    await state.clear()
    await state.set_state(Chat.active)
    await state.update_data(history=[])
    await message.answer("💬 Давайте переписываться на простом английском. Напишите что-нибудь, например: "
                         "<i>Hello! My name is …</i>\nОшибки я буду исправлять в конце ответа. Выход: /cancel")


@router.message(Chat.active, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    data = await state.get_data()
    history = data["history"]
    hist_text = "\n".join(f"{who}: {t}" for who, t in history) or "(empty)"
    try:
        turn = await gemini.generate_json(ChatTurn, render("chat", history=hist_text, text=message.text),
                                          await build_system(repo, user))
    except Exception as e:
        log.exception("chat turn failed")
        await message.answer(error_text(e))
        return

    text = html.escape(turn.reply)
    if turn.corrections:
        text += "\n\n✏️ <b>Исправления:</b>"
        for c in turn.corrections:
            text += f"\n❌ {html.escape(c.wrong)} → ✅ <b>{html.escape(c.right)}</b>\n   {html.escape(c.explanation)}"
            await repo.add_mistake(user["user_id"], c.wrong, c.right, c.explanation, type_="chat")
    await message.answer(text)
    await state.update_data(history=(history + [["Student", message.text], ["Partner", turn.reply]])[-MAX_HISTORY:])


@router.message(Chat.active, F.voice)
async def on_voice(message: Message) -> None:
    await message.answer("Здесь переписка текстом. Для голосового разговора — /talk.")
