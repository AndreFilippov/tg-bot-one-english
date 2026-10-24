import contextlib
import hashlib
import logging
import time
from pathlib import Path

import edge_tts

from services.audio import mp3_to_ogg_opus

log = logging.getLogger(__name__)


class TTSService:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def cache_key(text: str, voice: str, rate: int) -> str:
        return hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()

    async def synth(self, text: str, voice: str, rate: int = 0) -> Path:
        """Путь к ogg/opus с озвучкой. Одинаковые фразы берутся из кеша."""
        out = self.cache_dir / f"{self.cache_key(text, voice, rate)}.ogg"
        if out.exists():
            return out
        mp3 = out.with_suffix(".mp3")
        started = time.monotonic()
        try:
            await edge_tts.Communicate(text, voice, rate=f"{rate:+d}%").save(str(mp3))
            await mp3_to_ogg_opus(mp3, out)
            log.info("TTS готов за %.1f с", time.monotonic() - started)
        except Exception:
            with contextlib.suppress(OSError):
                out.unlink()
            raise
        finally:
            with contextlib.suppress(OSError):
                mp3.unlink()
        return out
