from services import text_match
from services.gemini import GeminiService
from services.models import AnswerCheck
from services.prompts import render


async def check_translation(gemini: GeminiService, system: str, topic: str, ru: str, expected: str,
                            answer: str, attempt: int = 1) -> AnswerCheck:
    """Сначала дешёвая локальная проверка, к Gemini обращаемся, только если ответ отличается от эталона."""
    if text_match.is_exact(answer, expected):
        return AnswerCheck(correct=True, corrected=answer)
    prompt = render("lesson_check", topic=topic, ru=ru, expected=expected, answer=answer, attempt=attempt)
    return await gemini.generate_json(AnswerCheck, prompt, system)
