from types import SimpleNamespace

import pytest
from google.genai import errors

from handlers.helpers import error_text
from services.gemini import GeminiError, GeminiRateLimit, GeminiService

DAILY = {"error": {"code": 429, "message": "Quota exceeded ... GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                   "details": [{"retryDelay": "66213s"}]}}


def make(models_behaviour, fallbacks=("b", "c")):
    svc = GeminiService("key", "a", "low", list(fallbacks))
    calls = []

    async def fake_generate(model, contents, config):
        calls.append(model)
        result = models_behaviour[model]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)

    svc.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate)))
    return svc, calls


async def test_daily_limit_switches_to_next_model_and_remembers():
    svc, calls = make({"a": errors.ClientError(429, DAILY), "b": "hello", "c": "x"})
    assert await svc.generate_text("hi", "sys") == "hello"
    assert calls == ["a", "b"]
    assert await svc.generate_text("hi", "sys") == "hello"
    assert calls == ["a", "b", "b"]  # исчерпанная модель больше не вызывается


async def test_unavailable_model_is_skipped():
    svc, calls = make({"a": errors.ClientError(403, {"error": {"code": 403, "message": "denied"}}),
                       "b": errors.ClientError(404, {"error": {"code": 404, "message": "gone"}}), "c": "ok"})
    assert await svc.generate_text("hi", "sys") == "ok"
    assert calls == ["a", "b", "c"]


async def test_all_models_exhausted_reports_daily_limit():
    err = errors.ClientError(429, DAILY)
    svc, _ = make({"a": err, "b": err, "c": err})
    with pytest.raises(GeminiRateLimit) as info:
        await svc.generate_text("hi", "sys")
    assert info.value.daily and info.value.retry_in == 66213
    assert "18 ч" in error_text(info.value)
    with pytest.raises(GeminiRateLimit):  # и без новых обращений к API
        await svc.generate_text("hi", "sys")


async def test_thinking_not_supported_retries_without_it():
    err = errors.ClientError(400, {"error": {"code": 400, "message": "Thinking level LOW is not supported"}})
    svc = GeminiService("key", "a", "low")
    seen = []

    async def fake_generate(model, contents, config):
        seen.append(config.thinking_config)
        if config.thinking_config is not None:
            raise err
        return SimpleNamespace(text="fine")

    svc.client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate)))
    assert await svc.generate_text("hi", "sys") == "fine"
    assert seen[0] is not None and seen[1] is None


async def test_other_errors_are_wrapped():
    svc, _ = make({"a": errors.ClientError(400, {"error": {"code": 400, "message": "bad"}})}, fallbacks=())
    with pytest.raises(GeminiError):
        await svc.generate_text("hi", "sys")
