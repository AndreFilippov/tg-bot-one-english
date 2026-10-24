"""Резервные копии базы SQLite (через встроенный backup API, безопасно при работающем боте)."""
import asyncio
import logging
import sqlite3
from pathlib import Path

from services import clock

log = logging.getLogger(__name__)


def _copy(src: Path, dst: Path) -> None:
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def prune(backup_dir: Path, keep: int) -> None:
    files = sorted(backup_dir.glob("bot-*.db"))
    for old in files[:-keep] if keep > 0 else files:
        old.unlink(missing_ok=True)


async def make_backup(db_path: Path, backup_dir: Path, keep: int = 7) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"bot-{clock.now().strftime('%Y%m%d-%H%M%S')}.db"
    await asyncio.to_thread(_copy, db_path, target)
    prune(backup_dir, keep)
    log.info("Резервная копия базы: %s", target.name)
    return target
