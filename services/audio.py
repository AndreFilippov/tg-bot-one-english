import asyncio
import contextlib
import os
import tempfile
from pathlib import Path

from aiogram import Bot


class AudioError(Exception):
    pass


async def mp3_to_ogg_opus(src: Path, dst: Path) -> None:
    """mp3 -> ogg/opus (моно, 48 кГц): формат, который принимает sendVoice."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1", "-application", "voip", str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg завершился с ошибкой: {err.decode(errors='ignore')[:300]}")


async def download_voice(bot: Bot, file_id: str) -> bytes:
    """Скачивает голосовое во временный файл, читает байты и удаляет файл."""
    file = await bot.get_file(file_id)
    fd, name = tempfile.mkstemp(suffix=".ogg")
    tmp = Path(name)
    os.close(fd)
    try:
        await bot.download_file(file.file_path, destination=tmp)
        return tmp.read_bytes()
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
