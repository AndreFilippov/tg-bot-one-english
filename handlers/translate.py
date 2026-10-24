"""/translate — переводчик: текст или голосовое, по-русски или по-английски. Английский вариант озвучивается."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user, say
from services.audio import download_voice
from services.gemini import GeminiService
from services.models import TranslateResult
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()


class Translate(StatesGroup):
    active = State()


async def do_translate(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                       user: dict, text: str | None = None, audio: bytes | None = None) -> None:
    if audio is not None:
        description = "The student's phrase is in the attached audio message (Russian or English)."
    else:
        description = f'The student\'s phrase: "{text}"'
    try:
        res = await gemini.generate_json(TranslateResult, render("translate", input_description=description),
                                         await build_system(repo, user), audio=audio)
    except Exception as e:
        log.exception("translate failed")
        await message.answer(error_text(e))
        return
    if not res.recognized or not res.target_text.strip():
        await message.answer("🙉 Не расслышал(а). Повторите, пожалуйста.")
        return
    to_english = res.source_lang.lower().startswith("ru")
    note = f"\n💬 {html.escape(res.note)}" if res.note.strip() else ""
    english, russian = (res.target_text, res.source_text) if to_english else (res.source_text, res.target_text)
    await state.update_data(tr_en=english, tr_ru=russian)
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ В словарь", callback_data="tr:add")]])
    summary = f"🇷🇺 {html.escape(russian)}\n🇺🇸 <b>{html.escape(english)}</b>{note}"
    if to_english:
        try:
            await say(message, tts, user, english, caption_prefix=summary, show_text=False, markup=markup)
            return
        except Exception:
            log.exception("translate tts failed")
    await message.answer(summary, reply_markup=markup)


@router.message(Command("translate"))
async def cmd_translate(message: Message, command: CommandObject, state: FSMContext, repo: Repo,
                        gemini: GeminiService, tts: TTSService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    if command.args and command.args.strip():
        await do_translate(message, state, repo, gemini, tts, user, text=command.args.strip())
        return
    await state.set_state(Translate.active)
    await message.answer("🔄 <b>Переводчик</b>. Пришлите фразу текстом или голосовым — по-русски (переведу на английский "
                         "и озвучу) или по-английски (переведу на русский). Выход: /cancel")


@router.message(Translate.active, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                  config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await do_translate(message, state, repo, gemini, tts, user, text=message.text)


@router.message(Translate.active, F.voice)
async def on_voice(message: Message, bot: Bot, state: FSMContext, repo: Repo, gemini: GeminiService,
                   tts: TTSService, config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    try:
        audio = await download_voice(bot, message.voice.file_id)
    except Exception:
        log.exception("voice download failed")
        await message.answer("😕 Не удалось скачать голосовое. Попробуйте ещё раз.")
        return
    await do_translate(message, state, repo, gemini, tts, user, audio=audio)


@router.callback_query(F.data == "tr:add")
async def on_add(cb: CallbackQuery, state: FSMContext, repo: Repo) -> None:
    await cb.answer()
    data = await state.get_data()
    if not data.get("tr_en"):
        await cb.message.answer("Нечего добавлять. Сначала переведите фразу: /translate")
        return
    added = await repo.add_word(cb.from_user.id, data["tr_en"], data["tr_ru"])
    await cb.message.answer("✅ Добавлено в словарь." if added else "Это уже есть в словаре.")
