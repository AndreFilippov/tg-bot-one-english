import json
import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

from aiogram.fsm.storage.base import StorageKey

from db import database
from db.repo import Repo
from services import backup, clock, profile, progress, vocab_io
from services.gemini import GeminiService
from services.sqlite_storage import SqliteStorage

TODAY = date(2026, 10, 24)


def days(**points):
    """days(d0=20, d1=5): d0 — сегодня, d1 — вчера и т. д."""
    return {(TODAY - timedelta(days=int(k[1:]))).isoformat(): {"points": v, "lessons": 0} for k, v in points.items()}


def test_streak_counts_consecutive_days_meeting_goal():
    assert progress.streak(days(d0=20, d1=25, d2=20), 20, TODAY) == 3
    assert progress.streak(days(d1=20, d2=20), 20, TODAY) == 2      # сегодня ещё не выполнено: считаем до вчера
    assert progress.streak(days(d0=20, d1=5, d2=20), 20, TODAY) == 1  # вчера цель не выполнена: серия прервана
    assert progress.streak({}, 20, TODAY) == 0


def test_week_bars_and_totals():
    d = days(d0=20, d1=5)
    bars = progress.week_bars(d, 20, TODAY)
    assert bars.count("🟩") == 1 and bars.count("🟨") == 1 and bars.count("⬜") == 5
    assert progress.week_totals(d, TODAY) == (25, 0)
    assert progress.progress_bar(5, 10) == "▰▰▰▰▰▱▱▱▱▱"


def test_vocab_split_and_parse():
    assert vocab_io.split_pair("apple яблоко") == ("apple", "яблоко")
    assert vocab_io.split_pair("яблоко - green apple") == ("green apple", "яблоко")
    assert vocab_io.split_pair("apple") is None
    assert vocab_io.split_pair("яблоко") is None
    rows = vocab_io.parse_words("word,translation,example\napple,яблоко,An apple.\ncat;кот\n,пусто\n")
    assert rows == [("apple", "яблоко", "An apple.")]
    assert vocab_io.parse_words("cat;кот;A cat.\ndog;собака") == [("cat", "кот", "A cat."), ("dog", "собака", "")]
    csv_bytes = vocab_io.to_csv([{"word": "cat", "translation": "кот", "example": None}])
    assert vocab_io.parse_words(csv_bytes.decode("utf-8-sig")) == [("cat", "кот", "")]


def test_profile_texts():
    user = {"nick": "Анна", "city": "Казань", "interests": "Футбол, Кино", "facts": json.dumps(["Has a cat"]),
            "ru_help": 0, "partner_role": "teacher"}
    text = profile.profile_for_prompt(user)
    assert "Анна" in text and "Казань" in text and "Футбол" in text and "Has a cat" in text
    assert profile.interests_of(user) == ["Футбол", "Кино"]
    assert "English" in profile.explain_lang(user) and profile.explain_lang({"ru_help": 1}) == "Russian"
    assert "strict" in profile.role_prompt(user)
    assert profile.profile_for_prompt({}) == "- (nothing known yet)"


async def test_repo_activity_mistakes_and_resets(tmp_path):
    db = await database.connect(tmp_path / "t.db")
    repo = Repo(db)
    await repo.get_or_create_user(1)
    assert await repo.add_activity(1, 5, 0) == (0, 5)
    assert await repo.add_activity(1, 20, 1) == (5, 25)
    day = (await repo.activity_days(1))[clock.today()]
    assert (day["points"], day["lessons"]) == (25, 1)

    for _ in range(3):
        await repo.add_mistake(1, "I fine", "I am fine", "x")
    await repo.add_mistake(1, "He go", "He goes", "y")
    await repo.add_mistake(1, "(не знаю)", "I am", "z")
    top = await repo.top_mistakes(1)
    assert (top[0]["wrong"], top[0]["n"]) == ("I fine", 3) and len(top) == 2

    await repo.add_fact(1, "Has a cat")
    await repo.add_fact(1, "Has a cat")
    assert json.loads((await repo.get_or_create_user(1))["facts"]) == ["Has a cat"]
    pid = await repo.add_pending_fact(1, "Likes tea")
    assert await repo.pop_pending_fact(pid, 2) is None
    assert await repo.pop_pending_fact(pid, 1) is None  # уже удалён при первой попытке

    await repo.add_word(1, "dog", "собака")
    await repo.add_api_usage("m1")
    await repo.add_api_usage("m1")
    assert await repo.api_usage_today() == {"m1": 2}
    await repo.reset(1, "progress")
    assert await repo.mistake_count(1) == 0 and not await repo.activity_days(1)
    assert (await repo.word_stats(1))["total"] == 1  # слова сохранились
    await db.close()


async def test_sqlite_storage_persists_state_and_data(tmp_path):
    db = await database.connect(tmp_path / "t.db")
    key = StorageKey(bot_id=1, chat_id=2, user_id=3)
    storage = SqliteStorage(db)
    await storage.set_state(key, "Talk:active")
    await storage.set_data(key, {"turns": 2, "history": [["A", "b"]]})
    await storage.update_data(key, {"turns": 3})
    again = SqliteStorage(db)  # «после перезапуска»: новый объект над той же базой
    assert await again.get_state(key) == "Talk:active"
    assert await again.get_data(key) == {"turns": 3, "history": [["A", "b"]]}
    await again.set_state(key, None)
    await again.set_data(key, {})
    assert await again.get_state(key) is None
    cur = await db.execute("SELECT COUNT(*) AS n FROM fsm")
    assert (await cur.fetchone())["n"] == 0  # пустая запись удалена
    await db.close()


async def test_backup_creates_valid_copy_and_prunes(tmp_path):
    db = await database.connect(tmp_path / "t.db")
    await Repo(db).get_or_create_user(7, "Anna")
    await db.close()
    target_dir = tmp_path / "b"
    for i in range(4):
        (target_dir).mkdir(exist_ok=True)
        (target_dir / f"bot-2020010{i}-000000.db").write_bytes(b"old")
    path = await backup.make_backup(tmp_path / "t.db", target_dir, keep=2)
    assert path.exists() and len(list(target_dir.glob("bot-*.db"))) == 2
    con = sqlite3.connect(path)
    assert con.execute("SELECT name FROM users WHERE user_id = 7").fetchone() == ("Anna",)
    con.close()


async def test_gemini_usage_hook_counts_successful_requests():
    counted = []

    async def hook(model):
        counted.append(model)

    svc = GeminiService("k", "a", "low", usage_hook=hook)

    async def fake_generate(model, contents, config):
        return SimpleNamespace(text="ok")

    svc.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate)))
    await svc.generate_text("hi", "sys")
    await svc.generate_text("hi", "sys")
    assert counted == ["a", "a"]
