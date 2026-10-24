"""Хранилище FSM aiogram в SQLite: текущий режим (урок, разговор…) переживает перезапуск бота."""
import json
from typing import Any, Mapping

import aiosqlite
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey


class SqliteStorage(BaseStorage):
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    @staticmethod
    def _key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}:{key.thread_id}:{key.business_connection_id}:{key.destiny}"

    async def _row(self, key: StorageKey):
        cur = await self.db.execute("SELECT state, data FROM fsm WHERE key = ?", (self._key(key),))
        return await cur.fetchone()

    async def _save(self, key: StorageKey, state: str | None, data: dict) -> None:
        if state is None and not data:
            await self.db.execute("DELETE FROM fsm WHERE key = ?", (self._key(key),))
        else:
            await self.db.execute(
                "INSERT INTO fsm (key, state, data) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET state = excluded.state, data = excluded.data",
                (self._key(key), state, json.dumps(data, ensure_ascii=False)))
        await self.db.commit()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._save(key, value, await self.get_data(key))

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self._row(key)
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self._save(key, await self.get_state(key), dict(data))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row = await self._row(key)
        return json.loads(row["data"]) if row and row["data"] else {}

    async def close(self) -> None:
        pass
