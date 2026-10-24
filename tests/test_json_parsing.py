import pytest

from services.models import ParseError, TalkSummary, TalkTurn, parse_model

GOOD = ('{"recognized": true, "transcript": "I am Anna", "is_correct": false,'
        ' "corrections": [{"wrong": "I Anna", "right": "I am Anna", "explanation": "Нужен глагол am."}],'
        ' "pronunciation_notes": "", "new_words": [{"word": "name", "translation": "имя"}],'
        ' "reply": "Nice to meet you! Where are you from?"}')


def test_plain_json():
    t = parse_model(GOOD, TalkTurn)
    assert t.transcript == "I am Anna"
    assert t.corrections[0].right == "I am Anna"
    assert t.new_words[0].example == ""


def test_fenced_json():
    t = parse_model(f"```json\n{GOOD}\n```", TalkTurn)
    assert t.reply.startswith("Nice")


def test_json_with_chatter():
    t = parse_model(f"Here you go: {GOOD} Hope it helps!", TalkTurn)
    assert t.is_correct is False


def test_defaults_for_unrecognized():
    t = parse_model('{"recognized": false}', TalkTurn)
    assert t.recognized is False and t.corrections == []


def test_summary():
    s = parse_model('{"rules": ["to be: I am"], "comment": "Молодец!"}', TalkSummary)
    assert s.rules == ["to be: I am"] and s.main_mistakes == []


@pytest.mark.parametrize("bad", ["", "no json here", "{broken", '{"corrections": "text"}', "[1, 2]"])
def test_bad_input_raises(bad):
    with pytest.raises(ParseError):
        parse_model(bad, TalkTurn)
