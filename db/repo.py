import json

import aiosqlite


class Repo:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    # --- users ---
    async def get_or_create_user(self, user_id: int, name: str = "", default_voice: str = "en-US-AriaNeural") -> dict:
        await self.db.execute(
            "INSERT OR IGNORE INTO users (user_id, name, voice) VALUES (?, ?, ?)", (user_id, name, default_voice)
        )
        await self.db.commit()
        cur = await self.db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return dict(await cur.fetchone())

    async def update_user(self, user_id: int, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(f"UPDATE users SET {cols} WHERE user_id = ?", (*fields.values(), user_id))
        await self.db.commit()

    # --- words ---
    async def add_word(self, user_id: int, word: str, translation: str, example: str = "") -> bool:
        cur = await self.db.execute(
            "INSERT OR IGNORE INTO words (user_id, word, translation, example) VALUES (?, ?, ?, ?)",
            (user_id, word.strip().lower(), translation.strip(), example.strip()),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def sample_words(self, user_id: int, limit: int = 10) -> list[str]:
        cur = await self.db.execute(
            "SELECT word FROM words WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, limit)
        )
        return [r["word"] for r in await cur.fetchall()]

    async def get_word(self, word_id: int) -> dict | None:
        cur = await self.db.execute("SELECT * FROM words WHERE id = ?", (word_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def due_word_ids(self, user_id: int, limit: int = 20) -> list[int]:
        cur = await self.db.execute(
            "SELECT id FROM words WHERE user_id = ? AND due_date <= date('now', 'localtime') "
            "ORDER BY due_date, id LIMIT ?", (user_id, limit))
        return [r["id"] for r in await cur.fetchall()]

    async def word_stats(self, user_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(due_date <= date('now', 'localtime')), 0) AS due, "
            "COALESCE(SUM(interval >= 21), 0) AS learned FROM words WHERE user_id = ?", (user_id,))
        return dict(await cur.fetchone())

    async def list_words(self, user_id: int, offset: int, limit: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM words WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, offset))
        return [dict(r) for r in await cur.fetchall()]

    async def update_word_srs(self, word_id: int, ease: float, interval: int, reps: int, due: str) -> None:
        await self.db.execute(
            "UPDATE words SET ease = ?, interval = ?, reps = ?, due_date = ? WHERE id = ?",
            (ease, interval, reps, due, word_id))
        await self.db.commit()

    # --- topic progress ---
    async def add_topic_result(self, user_id: int, topic_id: str, correct: int, total: int) -> None:
        await self.db.execute(
            "INSERT INTO topic_progress (user_id, topic_id, correct, total) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, topic_id) DO UPDATE SET correct = correct + excluded.correct, "
            "total = total + excluded.total", (user_id, topic_id, correct, total))
        await self.db.commit()

    async def set_topic_status(self, user_id: int, topic_id: str, status: str) -> None:
        await self.db.execute(
            "INSERT INTO topic_progress (user_id, topic_id, status) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, topic_id) DO UPDATE SET status = excluded.status", (user_id, topic_id, status))
        await self.db.commit()

    async def topic_progress(self, user_id: int) -> dict[str, dict]:
        cur = await self.db.execute("SELECT * FROM topic_progress WHERE user_id = ?", (user_id,))
        return {r["topic_id"]: dict(r) for r in await cur.fetchall()}

    async def users_with_reminder(self) -> list[dict]:
        cur = await self.db.execute("SELECT user_id, reminder_time FROM users WHERE reminder_time IS NOT NULL")
        return [dict(r) for r in await cur.fetchall()]

    # --- mistakes ---
    async def add_mistake(self, user_id: int, wrong: str, right: str, explanation: str,
                          session_id: int | None = None, type_: str = "grammar") -> None:
        await self.db.execute(
            "INSERT INTO mistakes (user_id, type, wrong, right, explanation, session_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, type_, wrong, right, explanation, session_id),
        )
        await self.db.commit()

    async def recent_mistakes(self, user_id: int, limit: int = 5) -> list[dict]:
        cur = await self.db.execute(
            "SELECT wrong, right, explanation FROM mistakes WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- sessions ---
    async def start_session(self, user_id: int, mode: str, scenario: str | None) -> int:
        cur = await self.db.execute(
            "INSERT INTO sessions (user_id, mode, scenario) VALUES (?, ?, ?)", (user_id, mode, scenario)
        )
        await self.db.commit()
        return cur.lastrowid

    async def save_session_progress(self, session_id: int, turns: int, history: list) -> None:
        await self.db.execute(
            "UPDATE sessions SET turns = ?, history = ? WHERE id = ?",
            (turns, json.dumps(history, ensure_ascii=False), session_id),
        )
        await self.db.commit()

    async def finish_session(self, session_id: int, summary: dict | None) -> None:
        await self.db.execute(
            "UPDATE sessions SET finished_at = CURRENT_TIMESTAMP, summary = ? WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False) if summary else None, session_id),
        )
        await self.db.commit()
