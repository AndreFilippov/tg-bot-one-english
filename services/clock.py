"""«Сегодня» в часовом поясе пользователя (TIMEZONE из .env), а не сервера."""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_tz: ZoneInfo | None = None


def configure(tz_name: str) -> None:
    global _tz
    try:
        _tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        _tz = None


def now() -> datetime:
    return datetime.now(_tz) if _tz else datetime.now()


def today_date() -> date:
    return now().date()


def today() -> str:
    return today_date().isoformat()
