from datetime import date

from services import srs, text_match
from services.scheduler import parse_hhmm

TODAY = date(2026, 1, 1)


def test_first_success_intervals():
    s1 = srs.review(2.5, 0, 0, 5, TODAY)
    assert (s1.reps, s1.interval, s1.due) == (1, 1, "2026-01-02")
    s2 = srs.review(s1.ease, s1.interval, s1.reps, 5, TODAY)
    assert (s2.reps, s2.interval) == (2, 3)
    s3 = srs.review(s2.ease, s2.interval, s2.reps, 5, TODAY)
    assert s3.reps == 3 and s3.interval > s2.interval


def test_failure_resets():
    s = srs.review(2.5, 20, 5, 1, TODAY)
    assert (s.reps, s.interval) == (0, 1)
    assert s.ease < 2.5


def test_ease_never_below_minimum():
    ease = 2.5
    for _ in range(20):
        ease = srs.review(ease, 1, 0, 0, TODAY).ease
    assert ease == srs.MIN_EASE


def test_easy_grows_faster_than_hard():
    easy = srs.review(2.5, 10, 3, 5, TODAY)
    hard = srs.review(2.5, 10, 3, 3, TODAY)
    assert easy.interval > hard.interval and easy.ease > hard.ease


def test_interval_always_grows_on_success():
    s = srs.review(1.3, 1, 3, 3, TODAY)
    assert s.interval >= 2


def test_text_match():
    assert text_match.is_exact("  Apple! ", "apple")
    assert text_match.is_exact("I’m fine.", "I'm fine")
    assert text_match.is_close("aple", "apple")
    assert not text_match.is_close("cat", "cap")  # короткие слова: опечатка = другое слово
    assert not text_match.is_close("banana", "apple")


def test_parse_hhmm():
    assert parse_hhmm("9:5") == "09:05"
    assert parse_hhmm(" 19:30 ") == "19:30"
    for bad in ("24:00", "12:60", "abc", "12", ""):
        assert parse_hhmm(bad) is None
