"""Упрощённый SM-2: интервал зависит от оценки ответа (0..5)."""
from dataclasses import dataclass
from datetime import date, timedelta

MIN_EASE = 1.3
FIRST_INTERVALS = {1: 1, 2: 3}  # дней после 1-го и 2-го успешного повторения


@dataclass(frozen=True)
class SrsState:
    ease: float
    interval: int
    reps: int
    due: str  # YYYY-MM-DD


def review(ease: float, interval: int, reps: int, quality: int, today: date | None = None) -> SrsState:
    """quality: 5 — легко, 4 — верно с небольшой неточностью, 3 — с трудом, <3 — не вспомнил."""
    quality = max(0, min(5, quality))
    today = today or date.today()
    ease = max(MIN_EASE, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if quality < 3:
        reps, interval = 0, 1
    else:
        reps += 1
        interval = FIRST_INTERVALS.get(reps) or max(interval + 1, round(interval * ease))
    return SrsState(round(ease, 2), interval, reps, (today + timedelta(days=interval)).isoformat())
