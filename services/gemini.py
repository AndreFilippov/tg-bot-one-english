import asyncio
import logging
import re
import time

from google import genai
from google.genai import errors, types

from services.models import ParseError, T, parse_model

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
REQUEST_TIMEOUT = 30  # сек на один запрос
BASE_DELAY = 4  # сек; задержки 4 -> 8 -> 16
DEFAULT_BLOCK = 6 * 3600  # на сколько отключаем модель, если срок сброса лимита неизвестен
UNAVAILABLE_BLOCK = 24 * 3600  # модель недоступна ключу (403/404)


class GeminiError(Exception):
    """Общая ошибка обращения к Gemini."""


class GeminiRateLimit(GeminiError):
    """Исчерпан лимит запросов (429). daily — дневной лимит, retry_in — через сколько секунд сбросится."""

    def __init__(self, message: str, daily: bool = False, retry_in: int = 0):
        super().__init__(message)
        self.daily = daily
        self.retry_in = retry_in


def is_daily_quota(e: errors.APIError) -> bool:
    return "PerDay" in str(e) or "per day" in str(e).lower()


def retry_seconds(e: errors.APIError) -> int:
    m = re.search(r"retryDelay\W+(\d+)s", str(e))
    return int(m.group(1)) if m else DEFAULT_BLOCK


class GeminiService:
    def __init__(self, api_key: str, model: str, thinking_level: str = "low", fallback_models: list[str] = (),
                 usage_hook=None):
        self.client = genai.Client(api_key=api_key)
        self.usage_hook = usage_hook  # async (model) -> None: счётчик запросов за день
        self.models = [model, *[m for m in fallback_models if m and m != model]]
        # "" — не передавать параметр; иначе minimal/low/medium/high (зависит от модели)
        self.thinking_level = thinking_level.upper() if thinking_level else None
        self._blocked_until: dict[str, float] = {}
        self._no_thinking: set[str] = set()

    @property
    def model(self) -> str:
        return self.models[0]

    def _block(self, model: str, seconds: int, reason: str) -> None:
        self._blocked_until[model] = time.monotonic() + seconds
        log.warning("Модель %s отключена на %d мин: %s", model, seconds // 60, reason)

    def _config(self, model: str, system: str, json_mode: bool) -> types.GenerateContentConfig:
        thinking = None
        if self.thinking_level and model not in self._no_thinking:
            thinking = types.ThinkingConfig(thinking_level=self.thinking_level)
        return types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
            temperature=0.7,
            thinking_config=thinking,  # для коротких реплик «размышления» только замедляют ответ
        )

    async def _call(self, contents: list, system: str, json_mode: bool) -> str:
        """Пробует модели по очереди: исчерпанные/недоступные пропускаются и временно отключаются."""
        now = time.monotonic()
        candidates = [m for m in self.models if self._blocked_until.get(m, 0) <= now]
        last_limit: GeminiRateLimit | None = None
        for model in candidates:
            try:
                return await self._call_model(model, contents, system, json_mode)
            except GeminiRateLimit as e:
                if not e.daily:
                    raise
                last_limit = e
            except errors.APIError as e:
                if getattr(e, "code", None) in (403, 404):
                    self._block(model, UNAVAILABLE_BLOCK, f"недоступна ключу ({e.code})")
                    continue
                raise GeminiError(str(e)) from e
        if last_limit or not candidates:
            wait = min((t - now for t in self._blocked_until.values()), default=0) if not candidates else 0
            raise GeminiRateLimit("все модели исчерпаны", daily=True,
                                  retry_in=int(last_limit.retry_in if last_limit else max(wait, 0)))
        raise GeminiError("нет доступных моделей Gemini (проверьте GEMINI_MODEL, см. check_gemini.py)")

    async def _call_model(self, model: str, contents: list, system: str, json_mode: bool) -> str:
        delay = BASE_DELAY
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                started = time.monotonic()
                resp = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=model, contents=contents, config=self._config(model, system, json_mode)),
                    REQUEST_TIMEOUT,
                )
                log.info("Gemini %s ответил за %.1f с", model, time.monotonic() - started)
                if self.usage_hook:
                    try:
                        await self.usage_hook(model)
                    except Exception:
                        log.exception("usage hook failed")
                return resp.text or ""
            except asyncio.TimeoutError:
                log.warning("Gemini %s не ответил за %d с (попытка %d/%d)", model, REQUEST_TIMEOUT, attempt,
                            MAX_ATTEMPTS)
                if attempt == MAX_ATTEMPTS:
                    raise GeminiError("timeout") from None
            except errors.APIError as e:
                code = getattr(e, "code", None)
                log.warning("Gemini %s error %s (attempt %d/%d): %s", model, code, attempt, MAX_ATTEMPTS,
                            str(e)[:300])
                if code == 400 and "thinking" in str(e).lower() and model not in self._no_thinking:
                    self._no_thinking.add(model)  # модель не поддерживает этот уровень — повторяем без него
                    continue
                if code == 429 and is_daily_quota(e):
                    secs = retry_seconds(e)
                    self._block(model, secs, "дневной лимит бесплатного тарифа")
                    raise GeminiRateLimit(str(e), daily=True, retry_in=secs) from e
                if code in (429, 500, 503) and attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if code == 429:
                    raise GeminiRateLimit(str(e)) from e
                raise
        raise GeminiError("unreachable")

    @staticmethod
    def _contents(prompt: str, audio: bytes | None) -> list:
        if audio is None:
            return [prompt]
        return [types.Part.from_bytes(data=audio, mime_type="audio/ogg"), prompt]

    async def generate_text(self, prompt: str, system: str) -> str:
        return (await self._call([prompt], system, json_mode=False)).strip()

    async def generate_json(self, cls: type[T], prompt: str, system: str, audio: bytes | None = None) -> T:
        """Запрос со строгим JSON. При ошибке разбора — один повторный запрос."""
        text = await self._call(self._contents(prompt, audio), system, json_mode=True)
        try:
            return parse_model(text, cls)
        except ParseError as e:
            log.warning("JSON parse failed, retrying once: %s | text=%r", e, text[:300])
        retry_prompt = (prompt + "\n\nIMPORTANT: your previous answer was not valid JSON. "
                        "Return ONLY one valid JSON object that matches the schema.")
        text = await self._call(self._contents(retry_prompt, audio), system, json_mode=True)
        try:
            return parse_model(text, cls)
        except ParseError as e:
            raise GeminiError(f"Gemini вернул некорректный JSON: {e}") from e
