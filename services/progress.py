"""Серия дней, недельная картинка и дневная цель."""
from datetime import date, timedelta

MET, PARTIAL, NONE = "🟩", "🟨", "⬜"
WEEKDAYS = "ПнВтСрЧтПтСбВс"


def _met(days: dict, d: date, goal: int) -> bool:
    return days.get(d.isoformat(), {}).get("points", 0) >= goal


def streak(days: dict[str, dict], goal: int, today: date) -> int:
    """Сколько дней подряд выполнена дневная цель. Если сегодня ещё не выполнена — считаем до вчера."""
    cursor = today if _met(days, today, goal) else today - timedelta(days=1)
    count = 0
    while _met(days, cursor, goal):
        count += 1
        cursor -= timedelta(days=1)
    return count


def week_bars(days: dict[str, dict], goal: int, today: date) -> str:
    """Последние 7 дней: два символа подпись дня недели + квадрат."""
    cells = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        points = days.get(d.isoformat(), {}).get("points", 0)
        mark = MET if points >= goal else PARTIAL if points > 0 else NONE
        cells.append(f"{WEEKDAYS[d.weekday() * 2: d.weekday() * 2 + 2]}{mark}")
    return " ".join(cells)


def week_totals(days: dict[str, dict], today: date) -> tuple[int, int]:
    """(очки за 7 дней, уроков за 7 дней)."""
    points = lessons = 0
    for i in range(7):
        row = days.get((today - timedelta(days=i)).isoformat(), {})
        points += row.get("points", 0)
        lessons += row.get("lessons", 0)
    return points, lessons


def progress_bar(done: int, total: int, width: int = 10) -> str:
    filled = round(width * done / total) if total else 0
    return "▰" * filled + "▱" * (width - filled)
