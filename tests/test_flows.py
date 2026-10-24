"""Сквозные проверки хендлеров без Telegram и Gemini: поддельная сессия бота и поддельный ИИ."""
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendAudio, SendMessage, SendVoice
from aiogram.types import Chat, Message, Update

from config import Config
from db import database
from db.repo import Repo
from handlers import chat, common, explain, lesson, review, settings, talk, test, words
from services.models import (AnswerCheck, ChatTurn, Correction, LessonContent, NewWord, TalkSummary, TalkTurn,
                             QuizSet)
from services.scheduler import Reminders

UID = 111


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, str]] = []  # (метод, текст/подпись)

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, (SendMessage, SendVoice, SendAudio)):
            text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
            self.sent.append((type(method).__name__, text))
            return Message(message_id=len(self.sent), date=datetime.now(), chat=Chat(id=UID, type="private"))
        return True


class FakeGemini:
    """Отвечает заготовками по типу схемы; последний ответ повторяется."""

    def __init__(self, **by_cls):
        self.by_cls = {k: list(v) for k, v in by_cls.items()}
        self.texts = ["Hello! What is your name?"]

    async def generate_text(self, prompt, system):
        return self.texts[0]

    async def generate_json(self, cls, prompt, system, audio=None):
        items = self.by_cls[cls.__name__]
        return items.pop(0) if len(items) > 1 else items[0]


class FakeTTS:
    def __init__(self, path):
        self.path = path

    async def synth(self, text, voice, rate=0):
        return self.path


@pytest.fixture
async def env(tmp_path):
    ogg = tmp_path / "x.ogg"
    ogg.write_bytes(b"OggS")
    db = await database.connect(tmp_path / "t.db")
    repo = Repo(db)
    session = MockSession()
    bot = Bot("123456:TEST", session=session)
    dp = Dispatcher(storage=MemoryStorage())
    routers = [common.router, settings.router, talk.router, lesson.router, review.router,
               chat.router, explain.router, words.router, test.router]
    for r in routers:  # роутеры — модульные синглтоны; в каждом тесте новый Dispatcher
        r._parent_router = None
    dp.include_routers(*routers)
    dp["config"] = Config("t", "k", "m", UID, "en-US-AriaNeural", "low", "UTC", ())
    dp["repo"] = repo
    dp["tts"] = FakeTTS(ogg)
    dp["reminders"] = Reminders(bot, repo, "UTC")

    class Env:
        pass

    e = Env()
    e.dp, e.bot, e.repo, e.session, e.n = dp, bot, repo, session, 0

    async def send(text=None, data=None):
        e.n += 1
        user = {"id": UID, "is_bot": False, "first_name": "T"}
        msg = {"message_id": 1000 + e.n, "date": 0, "chat": {"id": UID, "type": "private"}, "from": user}
        if data is None:
            msg["text"] = text
            if text.startswith("/"):
                msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            upd = {"update_id": e.n, "message": msg}
        else:
            upd = {"update_id": e.n, "callback_query": {"id": str(e.n), "from": user, "chat_instance": "c",
                                                       "data": data, "message": msg}}
        await dp.feed_update(bot, Update.model_validate(upd, context={"bot": bot}))

    e.send = send
    e.state = lambda: dp.fsm.get_context(bot, UID, UID)
    e.texts = lambda: "\n".join(t for _, t in session.sent)
    yield e
    await db.close()


def set_gemini(env, gemini):
    env.dp["gemini"] = gemini


async def test_onboarding_flow(env):
    set_gemini(env, FakeGemini())
    await env.send("/start")
    assert "Сначала короткий тест" in env.texts()
    wrong_at = 2  # на 3-м вопросе (артикли) отвечаем неверно
    from services import curriculum
    for i, q in enumerate(curriculum.load_placement()):
        pick = (q["answer"] + 1) % len(q["options"]) if i == wrong_at else q["answer"]
        await env.send(data=f"pt:{i}:{pick}")
    user = await env.repo.get_or_create_user(UID)
    assert user["current_topic"] == "articles"
    await env.send(data="st:t:20:00")
    user = await env.repo.get_or_create_user(UID)
    assert user["onboarded"] == 1 and user["reminder_time"] == "20:00"
    assert env.dp["reminders"].scheduler.get_job(f"remind_{UID}")
    await env.send("/start")
    assert "С возвращением" in env.texts()


async def test_full_lesson_flow(env):
    summary = TalkSummary(main_mistakes=["I Anna"], rules=["to be"], new_words=[NewWord(word="Cookie", translation="печенье")])
    turn = TalkTurn(transcript="I am fine", is_correct=False,
                    corrections=[Correction(wrong="I fine", right="I am fine", explanation="Нужен am.")],
                    new_words=[NewWord(word="fine", translation="хорошо")], reply="Nice. And you?")
    set_gemini(env, FakeGemini(
        LessonContent=[LessonContent(explanation_ru="Правило", examples=[], exercises=[
            {"ru": "Я студент", "en": "I am a student"}, {"ru": "Он врач", "en": "He is a doctor"}])],
        AnswerCheck=[AnswerCheck(correct=False, hint="Подумайте про is", explanation="He is.")],
        TalkTurn=[turn], TalkSummary=[summary]))
    await env.repo.get_or_create_user(UID)
    await env.repo.update_user(UID, onboarded=1, current_topic="to_be")
    await env.repo.add_word(UID, "apple", "яблоко", "An apple.")

    await env.send("/lesson")
    assert "яблоко" in env.texts()
    await env.send("apple")                       # повторение: верно
    assert "Верно" in env.texts()
    assert "Готовы к упражнениям" in env.texts()
    await env.send(data="ls:go")
    await env.send("I am a student")              # 1-е упражнение верно (локально)
    await env.send("He doctor")                   # 2-е: неверно -> подсказка
    assert "Подумайте про is" in env.texts()
    await env.send("He doctor")                   # снова неверно -> ответ
    assert "He is a doctor" in env.texts()
    assert "Мини-диалог по теме" in env.texts()   # 1/2 < 80% -> тема не пройдена, диалог всё равно идёт
    assert (await env.repo.get_or_create_user(UID))["current_topic"] == "to_be"
    for _ in range(3):
        await env.send("I fine")
    assert "Итоги разговора" in env.texts() and "Урок завершён" in env.texts()
    assert await env.state().get_state() is None
    assert await env.repo.recent_mistakes(UID)
    stats = await env.repo.word_stats(UID)
    assert stats["total"] == 3  # apple + fine + cookie
    assert any(kind == "SendVoice" for kind, _ in env.session.sent)


async def test_lesson_pass_advances_topic(env):
    set_gemini(env, FakeGemini(
        LessonContent=[LessonContent(explanation_ru="Правило", exercises=[{"ru": "Я", "en": "I am"}])],
        TalkTurn=[TalkTurn(transcript="x", reply="ok")], TalkSummary=[TalkSummary()]))
    await env.repo.get_or_create_user(UID)
    await env.repo.update_user(UID, onboarded=1, current_topic="to_be")
    await env.send("/lesson")
    await env.send(data="ls:go")
    await env.send("I am")
    assert (await env.repo.get_or_create_user(UID))["current_topic"] == "to_be_neg_q"
    assert "Тема пройдена" in env.texts()


async def test_chat_explain_settings_words(env):
    set_gemini(env, FakeGemini(ChatTurn=[ChatTurn(reply="Hi Anna!", corrections=[
        Correction(wrong="I Anna", right="I am Anna", explanation="Нужен am.")])]))
    env.dp["gemini"].texts = ["Правило: ..."]
    await env.send("/chat")
    await env.send("I Anna")
    assert "Hi Anna!" in env.texts() and "I am Anna" in env.texts()
    await env.send("/explain что такое артикль")
    assert "Правило" in env.texts()
    await env.send("/settings")
    await env.send(data="st:text")
    assert (await env.repo.get_or_create_user(UID))["show_text"] == 0
    await env.send(data="st:r:-30")
    assert (await env.repo.get_or_create_user(UID))["speech_rate"] == -30
    await env.send(data="st:v:3")
    assert (await env.repo.get_or_create_user(UID))["voice"] == "en-US-GuyNeural"
    await env.send(data="st:t:custom")
    await env.send("7:45")
    assert (await env.repo.get_or_create_user(UID))["reminder_time"] == "07:45"
    await env.repo.add_word(UID, "dog", "собака")
    await env.send("/words")
    await env.send(data="w:list:0")
    assert "dog" in env.texts()
    await env.send(data="wa:1")


async def test_weekly_test(env):
    qs = [{"topic_id": "to_be", "ru": "Я студент", "en": "I am a student"},
          {"topic_id": "to_be", "ru": "Он врач", "en": "He is a doctor"}]
    set_gemini(env, FakeGemini(QuizSet=[QuizSet(questions=qs)]))
    await env.repo.get_or_create_user(UID)
    await env.repo.update_user(UID, current_topic="to_be")
    await env.send("/test")
    await env.send("I am a student")
    await env.send(data="ts:idk")
    assert "Результат: 1/2" in env.texts()
    assert (await env.repo.get_or_create_user(UID))["last_test"]


async def test_talk_voice_forbidden_falls_back_to_audio(env):
    from aiogram.exceptions import TelegramBadRequest

    original = env.session.make_request

    async def forbidden(bot, method, timeout=None):
        if isinstance(method, SendVoice):
            raise TelegramBadRequest(method=method, message="Bad Request: VOICE_MESSAGES_FORBIDDEN")
        return await original(bot, method, timeout)

    env.session.make_request = forbidden
    set_gemini(env, FakeGemini())
    await env.send("/talk")
    await env.send(data="sc:intro")
    assert any(kind == "SendAudio" for kind, _ in env.session.sent)
