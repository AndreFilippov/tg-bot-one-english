import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompts"
LOGS_DIR = BASE_DIR / "logs"
TTS_CACHE_DIR = DATA_DIR / "tts_cache"
DB_PATH = DATA_DIR / "bot.db"
BACKUP_DIR = DATA_DIR / "backups"


# запасные модели: дневной лимит бесплатного тарифа считается отдельно для каждой модели
DEFAULT_FALLBACKS = "gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.5-flash"


@dataclass(frozen=True)
class Config:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    allowed_user_ids: tuple[int, ...]
    tts_voice: str
    gemini_thinking: str
    timezone: str
    gemini_fallback_models: tuple[str, ...]
    access_check: bool = False  # ACCESS_CHECK=on — отвечать только ALLOWED_USER_ID (и тем, кого добавил админ)
    backup_to_telegram: bool = True  # раз в неделю присылать копию базы админу (первому ID)


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")
    # Проверка по Telegram ID сейчас выключена по умолчанию; включается ACCESS_CHECK=on
    access_check = os.getenv("ACCESS_CHECK", "off").strip().lower() in ("on", "1", "true", "yes")
    required = ["BOT_TOKEN", "GEMINI_API_KEY", "GEMINI_MODEL"] + (["ALLOWED_USER_ID"] if access_check else [])
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise SystemExit(f"В .env не заполнено: {', '.join(missing)}")
    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        gemini_model=os.environ["GEMINI_MODEL"],
        allowed_user_ids=tuple(int(x) for x in re.split(r"[,\s]+", os.getenv("ALLOWED_USER_ID", "")) if x.strip().isdigit()),
        backup_to_telegram=os.getenv("BACKUP_TO_TELEGRAM", "on").strip().lower() in ("on", "1", "true", "yes"),
        access_check=access_check,
        tts_voice=os.getenv("TTS_VOICE", "en-US-AriaNeural"),
        gemini_thinking=os.getenv("GEMINI_THINKING", "low"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        gemini_fallback_models=tuple(m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", DEFAULT_FALLBACKS).split(",")
                                     if m.strip()),
    )
