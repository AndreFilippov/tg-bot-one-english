"""Инструменты словаря: /add, /due, /export, /import."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message

from config import Config
from db.repo import Repo
from handlers.helpers import build_system, error_text, get_user
from services import vocab_io
from services.gemini import GeminiService
from services.models import WordInfo
from services.prompts import render

log = logging.getLogger(__name__)
router = Router()
MAX_IMPORT_BYTES = 1_000_000


class Vocab(StatesGroup):
    importing = State()


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, state: FSMContext, repo: Repo, gemini: GeminiService,
                  config: Config) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.answer("Формат: <code>/add apple яблоко</code> или просто <code>/add apple</code> "
                             "(тогда я сам найду перевод и пример).")
        return
    await state.clear()
    user = await get_user(repo, message.from_user, config)
    pair = vocab_io.split_pair(text)
    if pair:
        word, translation, example = pair[0], pair[1], ""
    else:
        try:
            info = await gemini.generate_json(WordInfo, render("word_info", text=text), await build_system(repo, user))
        except Exception as e:
            log.exception("word info failed")
            await message.answer(error_text(e))
            return
        word, translation, example = info.word, info.translation, info.example
    added = await repo.add_word(user["user_id"], word, translation, example)
    line = f"<b>{html.escape(word)}</b> — {html.escape(translation)}"
    if example:
        line += f"\n<i>{html.escape(example)}</i>"
    await message.answer(("✅ Добавлено: " if added else "Такое слово уже есть: ") + line)


@router.message(Command("due"))
async def cmd_due(message: Message, command: CommandObject, repo: Repo) -> None:
    word = (command.args or "").strip()
    if not word:
        await message.answer("Формат: <code>/due apple</code>: слово сразу попадёт на повторение.")
        return
    row = await repo.find_word(message.from_user.id, word)
    if not row:
        await message.answer("Такого слова нет в словаре. Добавить: /add")
        return
    await repo.set_due_now(row["id"])
    await message.answer(f"🔁 «{html.escape(row['word'])}» поставлено на повторение. /words → «Повторить сейчас».")


@router.message(Command("export"))
async def cmd_export(message: Message, repo: Repo) -> None:
    words = await repo.all_words(message.from_user.id)
    if not words:
        await message.answer("Словарь пуст.")
        return
    await message.answer_document(BufferedInputFile(vocab_io.to_csv(words), filename="my_words.csv"),
                                  caption=f"📤 Ваш словарь: {len(words)} слов. Формат: word, translation, example.")


@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Vocab.importing)
    await message.answer("📥 Пришлите файл CSV (столбцы: word, translation, example) или напишите слова строками "
                         "<code>apple;яблоко;An apple.</code> Выход: /cancel")


async def save_rows(message: Message, repo: Repo, state: FSMContext, text: str) -> None:
    rows = vocab_io.parse_words(text)
    if not rows:
        await message.answer("Не нашёл ни одной строки вида «слово;перевод». Проверьте формат.")
        return
    added = 0
    for word, translation, example in rows:
        added += await repo.add_word(message.from_user.id, word, translation, example)
    await state.clear()
    await message.answer(f"✅ Импортировано новых слов: {added} из {len(rows)}.")


@router.message(Vocab.importing, F.document)
async def on_document(message: Message, bot: Bot, state: FSMContext, repo: Repo) -> None:
    doc = message.document
    if doc.file_size and doc.file_size > MAX_IMPORT_BYTES:
        await message.answer("Файл слишком большой (максимум 1 МБ).")
        return
    buf = await bot.download(doc)
    try:
        text = buf.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        await message.answer("Не получилось прочитать файл: сохраните его в кодировке UTF-8.")
        return
    await save_rows(message, repo, state, text)


@router.message(Vocab.importing, F.text & ~F.text.startswith("/"))
async def on_import_text(message: Message, state: FSMContext, repo: Repo) -> None:
    await save_rows(message, repo, state, message.text)
