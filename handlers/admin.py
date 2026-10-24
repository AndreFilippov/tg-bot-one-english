"""Команды администратора (первый ID из ALLOWED_USER_ID): доступ по списку, пользователи, резервная копия."""
import html
import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

import config as cfg
from config import Config
from db.repo import Repo
from services import backup

log = logging.getLogger(__name__)
router = Router()


def is_admin(message: Message, config: Config) -> bool:
    return bool(config.allowed_user_ids) and message.from_user.id == config.allowed_user_ids[0]


async def deny_non_admin(message: Message, config: Config) -> bool:
    if is_admin(message, config):
        return False
    text = ("Команда только для администратора (первый ID в ALLOWED_USER_ID)." if config.allowed_user_ids
            else "Администратор не задан: укажите ALLOWED_USER_ID в .env.")
    await message.answer(text)
    return True


def parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip()
    return int(arg) if arg.lstrip("-").isdigit() else None


@router.message(Command("allow"))
async def cmd_allow(message: Message, command: CommandObject, repo: Repo, config: Config) -> None:
    if await deny_non_admin(message, config):
        return
    user_id = parse_id(command)
    if user_id is None:
        await message.answer("Формат: <code>/allow 123456789</code> (Telegram ID человека, его покажет @userinfobot).")
        return
    await repo.allow(user_id, message.from_user.id)
    note = "" if config.access_check else "\n(Проверка доступа сейчас выключена: ACCESS_CHECK=off, бот отвечает всем.)"
    await message.answer(f"✅ Доступ открыт: {user_id}{note}")


@router.message(Command("deny"))
async def cmd_deny(message: Message, command: CommandObject, repo: Repo, config: Config) -> None:
    if await deny_non_admin(message, config):
        return
    user_id = parse_id(command)
    if user_id is None:
        await message.answer("Формат: <code>/deny 123456789</code>")
        return
    if user_id in config.allowed_user_ids:
        await message.answer("Этот ID задан в .env, его можно убрать только там.")
        return
    await repo.deny(user_id)
    await message.answer(f"🚫 Доступ закрыт: {user_id}")


@router.message(Command("users"))
async def cmd_users(message: Message, repo: Repo, config: Config) -> None:
    if await deny_non_admin(message, config):
        return
    allowed = await repo.list_allowed()
    users = await repo.list_users()
    lines = [f"🔐 Проверка доступа: <b>{'включена' if config.access_check else 'выключена'}</b>",
             f"Из .env: {', '.join(map(str, config.allowed_user_ids)) or '—'}",
             f"Добавлены командой /allow: {', '.join(map(str, allowed)) or '—'}", "", f"👥 Пользователей: {len(users)}"]
    for u in users[:30]:
        who = html.escape(u["nick"] or u["name"] or "—")
        lines.append(f"• {u['user_id']} — {who}, тема {u['current_topic']}")
    await message.answer("\n".join(lines))


@router.message(Command("backup"))
async def cmd_backup(message: Message, config: Config) -> None:
    if await deny_non_admin(message, config):
        return
    path = await backup.make_backup(cfg.DB_PATH, cfg.BACKUP_DIR)
    await message.answer_document(FSInputFile(path), caption="💾 Резервная копия базы. Восстановление: остановите бота и "
                                                              "замените data/bot.db этим файлом.")
