import json

import aiosqlite

from services import clock

PROFILE_FIELDS = ("nick", "age", "city", "occupation", "goal", "interests", "facts")


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
            "INSERT OR IGNORE INTO words (user_id, word, translation, example, due_date) VALUES (?, ?, ?, ?, ?)",
            (user_id, word.strip().lower(), translation.strip(), example.strip(), clock.today()),
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
            "SELECT id FROM words WHERE user_id = ? AND due_date <= ? ORDER BY due_date, id LIMIT ?",
            (user_id, clock.today(), limit))
        return [r["id"] for r in await cur.fetchall()]

    async def word_stats(self, user_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(due_date <= ?), 0) AS due, "
            "COALESCE(SUM(interval >= 21), 0) AS learned FROM words WHERE user_id = ?", (clock.today(), user_id))
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

    # --- profile and facts ---
    async def add_fact(self, user_id: int, text: str) -> None:
        user = await self.get_or_create_user(user_id)
        facts = json.loads(user.get("facts") or "[]")
        text = text.strip()
        if text and text not in facts:
            await self.update_user(user_id, facts=json.dumps((facts + [text])[-30:], ensure_ascii=False))

    async def remove_fact(self, user_id: int, index: int) -> None:
        user = await self.get_or_create_user(user_id)
        facts = json.loads(user.get("facts") or "[]")
        if 0 <= index < len(facts):
            del facts[index]
            await self.update_user(user_id, facts=json.dumps(facts, ensure_ascii=False))

    async def add_pending_fact(self, user_id: int, text: str) -> int:
        cur = await self.db.execute("INSERT INTO pending_facts (user_id, text) VALUES (?, ?)", (user_id, text))
        await self.db.commit()
        return cur.lastrowid

    async def pop_pending_fact(self, fact_id: int, user_id: int) -> str | None:
        cur = await self.db.execute("SELECT text FROM pending_facts WHERE id = ? AND user_id = ?", (fact_id, user_id))
        row = await cur.fetchone()
        await self.db.execute("DELETE FROM pending_facts WHERE id = ?", (fact_id,))
        await self.db.commit()
        return row["text"] if row else None

    # --- activity: points, lessons, streak ---
    async def add_activity(self, user_id: int, points: int = 0, lessons: int = 0) -> tuple[int, int]:
        """Возвращает (очки сегодня до, очки сегодня после)."""
        day = clock.today()
        cur = await self.db.execute("SELECT points FROM activity WHERE user_id = ? AND day = ?", (user_id, day))
        row = await cur.fetchone()
        before = row["points"] if row else 0
        await self.db.execute(
            "INSERT INTO activity (user_id, day, points, lessons) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET points = points + excluded.points, "
            "lessons = lessons + excluded.lessons", (user_id, day, points, lessons))
        await self.db.commit()
        return before, before + points

    async def activity_days(self, user_id: int, limit: int = 120) -> dict[str, dict]:
        cur = await self.db.execute(
            "SELECT day, points, lessons FROM activity WHERE user_id = ? ORDER BY day DESC LIMIT ?",
            (user_id, limit))
        return {r["day"]: dict(r) for r in await cur.fetchall()}

    # --- mistakes and sessions: analytics ---
    async def top_mistakes(self, user_id: int, limit: int = 5) -> list[dict]:
        cur = await self.db.execute(
            "SELECT wrong, right, explanation, COUNT(*) AS n FROM mistakes "
            "WHERE user_id = ? AND wrong NOT LIKE '(%' AND right IS NOT NULL AND right <> '' "
            "GROUP BY lower(wrong), lower(right) ORDER BY n DESC, MAX(id) DESC LIMIT ?", (user_id, limit))
        return [dict(r) for r in await cur.fetchall()]

    async def session_stats(self, user_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS talks, COALESCE(SUM(turns), 0) AS turns FROM sessions "
            "WHERE user_id = ? AND mode = 'talk' AND turns > 0", (user_id,))
        return dict(await cur.fetchone())

    async def mistake_count(self, user_id: int) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS n FROM mistakes WHERE user_id = ?", (user_id,))
        return (await cur.fetchone())["n"]

    # --- words: tools ---
    async def find_word(self, user_id: int, word: str) -> dict | None:
        cur = await self.db.execute("SELECT * FROM words WHERE user_id = ? AND word = ?",
                                    (user_id, word.strip().lower()))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_due_now(self, word_id: int) -> None:
        await self.db.execute("UPDATE words SET due_date = ? WHERE id = ?", (clock.today(), word_id))
        await self.db.commit()

    async def all_words(self, user_id: int) -> list[dict]:
        cur = await self.db.execute("SELECT word, translation, example FROM words WHERE user_id = ? ORDER BY id",
                                    (user_id,))
        return [dict(r) for r in await cur.fetchall()]

    # --- access list ---
    async def is_allowed(self, user_id: int) -> bool:
        cur = await self.db.execute("SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

    async def allow(self, user_id: int, added_by: int) -> None:
        await self.db.execute("INSERT OR IGNORE INTO allowed_users (user_id, added_by) VALUES (?, ?)",
                              (user_id, added_by))
        await self.db.commit()

    async def deny(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM allowed_users WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def list_allowed(self) -> list[int]:
        cur = await self.db.execute("SELECT user_id FROM allowed_users ORDER BY created_at")
        return [r["user_id"] for r in await cur.fetchall()]

    async def list_users(self) -> list[dict]:
        cur = await self.db.execute("SELECT user_id, name, nick, current_topic FROM users ORDER BY created_at")
        return [dict(r) for r in await cur.fetchall()]

    # --- API usage counter ---
    async def add_api_usage(self, model: str) -> None:
        await self.db.execute(
            "INSERT INTO api_usage (day, model, count) VALUES (?, ?, 1) "
            "ON CONFLICT(day, model) DO UPDATE SET count = count + 1", (clock.today(), model))
        await self.db.commit()

    async def api_usage_today(self) -> dict[str, int]:
        cur = await self.db.execute("SELECT model, count FROM api_usage WHERE day = ?", (clock.today(),))
        return {r["model"]: r["count"] for r in await cur.fetchall()}

    # --- resets ---
    async def reset(self, user_id: int, what: str) -> None:
        """what: words | progress | profile | all."""
        q = self.db.execute
        if what == "words":
            await q("DELETE FROM words WHERE user_id = ?", (user_id,))
        elif what == "progress":
            await q("DELETE FROM topic_progress WHERE user_id = ?", (user_id,))
            await q("DELETE FROM activity WHERE user_id = ?", (user_id,))
            await q("DELETE FROM mistakes WHERE user_id = ?", (user_id,))
            await q("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            await q("UPDATE users SET current_topic = 'alphabet', level = 'A1', last_test = NULL WHERE user_id = ?",
                    (user_id,))
        elif what == "profile":
            await q("UPDATE users SET nick = NULL, age = NULL, city = NULL, occupation = NULL, goal = NULL, "
                    "interests = '', facts = '[]' WHERE user_id = ?", (user_id,))
            await q("DELETE FROM pending_facts WHERE user_id = ?", (user_id,))
        elif what == "all":
            for table in ("words", "topic_progress", "mistakes", "sessions", "activity", "pending_facts", "users"):
                await q(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        await self.db.commit()
