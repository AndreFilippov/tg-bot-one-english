"""Pydantic-схемы ответов Gemini и разбор JSON."""
import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ParseError(Exception):
    pass


class Correction(BaseModel):
    wrong: str
    right: str
    explanation: str = ""


class NewWord(BaseModel):
    word: str
    translation: str
    example: str = ""


class TalkTurn(BaseModel):
    recognized: bool = True
    transcript: str = ""
    is_correct: bool = True
    corrections: list[Correction] = []
    pronunciation_notes: str = ""
    new_words: list[NewWord] = []
    reply: str = ""


class TalkSummary(BaseModel):
    main_mistakes: list[str] = []
    rules: list[str] = []
    new_words: list[NewWord] = []
    facts: list[str] = []
    comment: str = ""


class Transcript(BaseModel):
    recognized: bool = True
    transcript: str = ""


class Example(BaseModel):
    en: str
    ru: str = ""


class Exercise(BaseModel):
    ru: str
    en: str


class LessonContent(BaseModel):
    explanation_ru: str
    examples: list[Example] = []
    exercises: list[Exercise] = []


class AnswerCheck(BaseModel):
    correct: bool
    corrected: str = ""
    hint: str = ""
    explanation: str = ""


class ChatTurn(BaseModel):
    reply: str
    corrections: list[Correction] = []


class TestQuestion(BaseModel):
    topic_id: str
    ru: str
    en: str


class PronunciationCheck(BaseModel):
    recognized: bool = True
    transcript: str = ""
    score: int = 0
    issues: list[str] = []
    tip: str = ""


class ListenQuestion(BaseModel):
    q: str
    options: list[str]
    answer: int


class ListenSet(BaseModel):
    story: str
    questions: list[ListenQuestion] = []


class TranslateResult(BaseModel):
    recognized: bool = True
    source_text: str = ""
    source_lang: str = "ru"
    target_text: str = ""
    note: str = ""


class PracticeSet(BaseModel):
    exercises: list[Exercise] = []


class WordInfo(BaseModel):
    word: str
    translation: str
    example: str = ""


class QuizSet(BaseModel):
    questions: list[TestQuestion] = []


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_model(text: str, cls: type[T]) -> T:
    """Достаёт JSON из ответа (в т.ч. из ```-блока) и валидирует по схеме."""
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ParseError("JSON не найден в ответе")
        cleaned = cleaned[start:end + 1]
    try:
        return cls.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ParseError(str(e)) from e
