"""Ежедневные напоминания со счётчиком слов на повторение."""
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db.repo import Repo
from services import clock, progress

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

    def add_cron(self, func, job_id: str, hour: int, minute: int = 0, day_of_week: str | None = None) -> None:
        """Служебные задачи (резервные копии)."""
        self.scheduler.add_job(func, CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week, timezone=self.tz),
                               id=job_id, replace_existing=True)

    async def build_text(self, user_id: int) -> str:
        user = await self.repo.get_or_create_user(user_id)
        today = clock.today_date()
        goal = user["daily_goal"] or 20
        days = await self.repo.activity_days(user_id)
        done = days.get(today.isoformat(), {}).get("points", 0)
        n_streak = progress.streak(days, goal, today)
        due = (await self.repo.word_stats(user_id))["due"]
        name = f", {user['nick']}" if user.get("nick") else ""
        lines = [f"⏰ Время учить английский{name}!"]
        lines.append(f"Слов на повторение: <b>{due}</b>. /words" if due else "Слов на повторение нет.")
        if done >= goal:
            lines.append(f"🎯 Цель дня уже выполнена ({done}/{goal}). Серия: {n_streak} дн.")
        elif n_streak:
            lines.append(f"🔥 Серия {n_streak} дн.: не прерывайте! Сегодня {done}/{goal}.")
        else:
            lines.append(f"🎯 Цель дня: {done}/{goal}.")
        if today.weekday() == 6:  # воскресенье: недельная сводка
            points, lessons = progress.week_totals(days, today)
            lines.append(f"\n📅 <b>Итоги недели</b>: очков {points}, уроков {lessons}\n"
                         f"{progress.week_bars(days, goal, today)}")
        lines.append("/lesson — урок на сегодня")
        return "\n".join(lines)

    async def send(self, user_id: int) -> None:
        try:
            await self.bot.send_message(user_id, await self.build_text(user_id))
        except Exception:
            log.exception("Не удалось отправить напоминание")
