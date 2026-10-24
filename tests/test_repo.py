from db import database
from db.repo import Repo


async def test_user_words_and_mistakes(tmp_path):
    db = await database.connect(tmp_path / "t.db")
    repo = Repo(db)
    user = await repo.get_or_create_user(1, "Test")
    assert user["speech_rate"] == -20 and user["show_text"] == 1

    assert await repo.add_word(1, "Apple", "яблоко", "An apple.") is True
    assert await repo.add_word(1, "apple", "яблоко") is False  # дубль
    assert await repo.sample_words(1) == ["apple"]

    await repo.add_mistake(1, "I Anna", "I am Anna", "Нужен am.")
    assert (await repo.recent_mistakes(1))[0]["right"] == "I am Anna"

    sid = await repo.start_session(1, "talk", "cafe")
    await repo.save_session_progress(sid, 2, [["Partner", "Hi"]])
    await repo.finish_session(sid, {"comment": "ok"})
    await db.close()
