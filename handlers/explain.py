import html
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user
from services.gemini import GeminiService
from services.prompts import render

log = logging.getLogger(__name__)
router = Router()


@router.message(Command("explain"))
async def cmd_explain(message: Message, command: CommandObject, repo: Repo, gemini: GeminiService,
                      config: Config) -> None:
    question = (command.args or "").strip()
    if not question:
        await message.answer("Напишите вопрос после команды, например:\n<code>/explain когда нужен артикль the?</code>")
        return
    user = await get_user(repo, message.from_user, config)
    try:
        answer = await gemini.generate_text(render("explain", question=question), await build_system(repo, user))
    except Exception as e:
        log.exception("explain failed")
        await message.answer(error_text(e))
        return
    await message.answer(html.escape(answer))
