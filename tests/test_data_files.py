from config import PROMPTS_DIR
from services import curriculum
from services.models import (AnswerCheck, ChatTurn, LessonContent, QuizSet, Transcript, parse_model)


def test_curriculum_is_consistent():
    topics = curriculum.load_topics()
    ids = [t["id"] for t in topics]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    assert all(t["title"] and t["focus"] for t in topics)
    assert curriculum.next_topic_id(ids[0]) == ids[1]
    assert curriculum.next_topic_id(ids[-1]) is None


def test_placement_topics_exist():
    ids = {t["id"] for t in curriculum.load_topics()}
    for q in curriculum.load_placement():
        assert q["topic"] in ids
        assert 0 <= q["answer"] < len(q["options"])


def test_scenarios_have_required_fields():
    for sid, s in curriculum.load_scenarios().items():
        assert s["id"] == sid and s["title"] and s["goal"] and s["emoji"]


def test_prompts_exist_and_have_no_unknown_placeholders():
    names = ["system_teacher", "talk_opening", "talk_turn", "talk_translate", "talk_hint", "talk_summary",
             "lesson_content", "lesson_check", "explain", "chat", "test_generate", "voice_transcribe"]
    for n in names:
        assert (PROMPTS_DIR / f"{n}.txt").read_text(encoding="utf-8").strip(), n


def test_new_models_parse():
    assert parse_model('{"correct": false, "hint": "h"}', AnswerCheck).hint == "h"
    assert parse_model('{"reply": "Hi", "corrections": []}', ChatTurn).reply == "Hi"
    assert parse_model('{"recognized": true, "transcript": "cat"}', Transcript).transcript == "cat"
    ls = parse_model('{"explanation_ru": "x", "examples": [{"en": "a"}], "exercises": [{"ru": "я", "en": "I"}]}',
                     LessonContent)
    assert ls.exercises[0].en == "I"
    ts = parse_model('{"questions": [{"topic_id": "to_be", "ru": "я", "en": "I am"}]}', QuizSet)
    assert ts.questions[0].topic_id == "to_be"
