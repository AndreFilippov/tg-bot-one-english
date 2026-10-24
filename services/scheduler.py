"""Ежедневные напоминания со счётчиком слов на повторение."""
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db.repo import Repo

log = logging.getLogger(__name__)


def parse_hhmm(text: str) -> str | None:
    """'9:5' / '09:05' -> '09:05'; неверное время -> None."""
    try:
        h, m = text.strip().split(":")
        h, m = int(h), int(m)
    except ValueError:
        return None
    return f"{h:02d}:{m:02d}" if 0 <= h < 24 and 0 <= m < 60 else None


class Reminders:
    def __init__(self, bot: Bot, repo: Repo, tz_name: str):
        try:
            self.tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            log.warning("Неизвестный часовой пояс %r, использую UTC", tz_name)
            self.tz = ZoneInfo("UTC")
        self.bot, self.repo = bot, repo
        self.scheduler = AsyncIOScheduler(timezone=self.tz)

    async def start(self) -> None:
        for u in await self.repo.users_with_reminder():
            self.schedule(u["user_id"], u["reminder_time"])
        self.scheduler.start()

    def schedule(self, user_id: int, hhmm: str | None) -> None:
        job_id = f"remind_{user_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        if not hhmm:
            return
        hour, minute = map(int, hhmm.split(":"))
        self.scheduler.add_job(self.send, CronTrigger(hour=hour, minute=minute, timezone=self.tz),
                               args=[user_id], id=job_id, replace_existing=True)

    async def send(self, user_id: int) -> None:
        try:
            due = (await self.repo.word_stats(user_id))["due"]
            words = f"Слов на повторение: <b>{due}</b>. /words" if due else "Слов на повторение нет."
            await self.bot.send_message(user_id, f"⏰ Время учить английский!\n{words}\n/lesson — урок на сегодня")
        except Exception:
            log.exception("Не удалось отправить напоминание")
