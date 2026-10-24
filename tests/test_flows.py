"""Сквозные проверки хендлеров без Telegram и Gemini: поддельная сессия бота и поддельный ИИ.
FSM хранится в SqliteStorage, поэтому заодно проверяется, что данные режимов сериализуются в JSON."""
from dataclasses import replace
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, SendAudio, SendDocument, SendMessage, SendVoice
from aiogram.types import Chat, File, Message, Update

from config import Config
from db import database
from db.repo import Repo
from handlers import (admin, chat, common, explain, lesson, listen, profile, progress, pronounce, reset, review,
                      settings, talk, test, translate, vocab, weak, words)
from services import curriculum
from services.models import (AnswerCheck, ChatTurn, Correction, LessonContent, ListenQuestion, ListenSet, NewWord,
                             PracticeSet, PronunciationCheck, QuizSet, TalkSummary, TalkTurn, TranslateResult,
                             WordInfo)
from services.scheduler import Reminders
from services.sqlite_storage import SqliteStorage

UID = 111
ROUTERS = [common, settings, profile, progress, talk, lesson, review, chat, explain, words, test, weak, pronounce,
           listen, translate, vocab, reset, admin]


class MockSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[tuple[str, str]] = []  # (метод, текст/подпись)

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b"OggS"

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="voice/f.ogg")
        if isinstance(method, (SendMessage, SendVoice, SendAudio, SendDocument)):
            text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
            self.sent.append((type(method).__name__, text))
            return Message(message_id=len(self.sent), date=datetime.now(), chat=Chat(id=UID, type="private"))
        return True


class FakeGemini:
    """Отвечает заготовками по имени схемы; последний ответ повторяется."""

    def __init__(self, **by_cls):
        self.by_cls = {k: list(v) for k, v in by_cls.items()}
        self.texts = ["Hello! What is your name?"]
        self.calls = 0

    async def generate_text(self, prompt, system):
        self.calls += 1
        return self.texts[0]

    async def generate_json(self, cls, prompt, system, audio=None):
        self.calls += 1
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
    dp = Dispatcher(storage=SqliteStorage(db))
    routers = [m.router for m in ROUTERS]
    for r in routers:  # роутеры — модульные синглтоны; в каждом тесте новый Dispatcher
        r._parent_router = None
    dp.include_routers(*routers)
    dp["config"] = Config("t", "k", "m", (UID,), "en-US-AriaNeural", "low", "UTC", ())
    dp["repo"] = repo
    dp["tts"] = FakeTTS(ogg)
    dp["reminders"] = Reminders(bot, repo, "UTC")
    dp["gemini"] = FakeGemini()

    class Env:
        pass

    e = Env()
    e.dp, e.bot, e.repo, e.session, e.n = dp, bot, repo, session, 0

    async def send(text=None, data=None, voice=False):
        e.n += 1
        user = {"id": UID, "is_bot": False, "first_name": "T"}
        msg = {"message_id": 1000 + e.n, "date": 0, "chat": {"id": UID, "type": "private"}, "from": user}
        if data is not None:
            upd = {"update_id": e.n, "callback_query": {"id": str(e.n), "from": user, "chat_instance": "c",
                                                       "data": data, "message": msg}}
        else:
            if voice:
                msg["voice"] = {"file_id": "f", "file_unique_id": "u", "duration": 1}
            else:
                msg["text"] = text
                if text.startswith("/"):
                    msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
            upd = {"update_id": e.n, "message": msg}
        await dp.feed_update(bot, Update.model_validate(upd, context={"bot": bot}))

    e.send = send
    e.state = lambda: dp.fsm.get_context(bot, UID, UID)
    e.texts = lambda: "\n".join(t for _, t in session.sent)
    yield e
    await db.close()


def set_gemini(env, gemini):
    env.dp["gemini"] = gemini


async def make_user(env, **fields):
    await env.repo.get_or_create_user(UID)
    await env.repo.update_user(UID, onboarded=1, **fields)


async def test_onboarding_flow_with_profile(env):
    await env.send("/start")
    assert "Сначала короткий тест" in env.texts()
    wrong_at = 2  # на 3-м вопросе (артикли) отвечаем неверно
    for i, q in enumerate(curriculum.load_placement()):
        pick = (q["answer"] + 1) % len(q["options"]) if i == wrong_at else q["answer"]
        await env.send(data=f"pt:{i}:{pick}")
    user = await env.repo.get_or_create_user(UID)
    assert user["current_topic"] == "articles"
    assert "Как вас зовут" in env.texts()
    await env.send("Анна")
    await env.send(data="pf:skip")            # город пропускаем
    await env.send("программист")
    await env.send(data="pg:0")               # цель: путешествия
    await env.send(data="pi:0")
    await env.send(data="pi:ok")
    assert "время ежедневного" in env.texts()
    user = await env.repo.get_or_create_user(UID)
    assert (user["nick"], user["city"], user["occupation"], user["goal"], user["interests"]) == (
        "Анна", None, "программист", "Путешествия", "Путешествия")
    await env.send(data="st:t:20:00")
    user = await env.repo.get_or_create_user(UID)
    assert user["onboarded"] == 1 and user["reminder_time"] == "20:00"
    assert env.dp["reminders"].scheduler.get_job(f"remind_{UID}")
    await env.send("/start")
    assert "С возвращением" in env.texts()


async def test_profile_edit_and_facts(env):
    await make_user(env, nick="Анна")
    await env.send("/profile")
    assert "Анна" in env.texts()
    await env.send(data="pe:city")
    await env.send("Казань")
    assert (await env.repo.get_or_create_user(UID))["city"] == "Казань"
    await env.send(data="pa:fact")
    await env.send("У меня есть кошка Том")
    assert "кошка" in (await env.repo.get_or_create_user(UID))["facts"]
    await env.send(data="pe:facts")
    await env.send(data="pd:0")
    assert (await env.repo.get_or_create_user(UID))["facts"] == "[]"


async def test_full_lesson_flow(env):
    summary = TalkSummary(main_mistakes=["I Anna"], rules=["to be"],
                          new_words=[NewWord(word="Cookie", translation="печенье")],
                          facts=["The student has a cat named Tom"])
    turn = TalkTurn(transcript="I am fine", is_correct=False,
                    corrections=[Correction(wrong="I fine", right="I am fine", explanation="Нужен am.")],
                    new_words=[NewWord(word="fine", translation="хорошо")], reply="Nice. And you?")
    set_gemini(env, FakeGemini(
        LessonContent=[LessonContent(explanation_ru="Правило", examples=[], exercises=[
            {"ru": "Я студент", "en": "I am a student"}, {"ru": "Он врач", "en": "He is a doctor"}])],
        AnswerCheck=[AnswerCheck(correct=False, hint="Подумайте про is", explanation="He is.")],
        TalkTurn=[turn], TalkSummary=[summary]))
    await make_user(env, current_topic="to_be")
    await env.repo.add_word(UID, "apple", "яблоко", "An apple.")

    await env.send("/lesson")
    assert "яблоко" in env.texts()
    await env.send("apple")                       # повторение: верно
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
    assert "Запомнить о вас" in env.texts()       # предложен факт
    await env.send(data="fk:1")
    assert "cat named Tom" in (await env.repo.get_or_create_user(UID))["facts"]
    assert await env.state().get_state() is None
    assert await env.repo.recent_mistakes(UID)
    assert (await env.repo.word_stats(UID))["total"] == 3  # apple + fine + cookie
    assert any(kind == "SendVoice" for kind, _ in env.session.sent)
    assert (await env.repo.activity_days(UID))  # очки и урок записаны


async def test_lesson_pass_advances_topic(env):
    set_gemini(env, FakeGemini(
        LessonContent=[LessonContent(explanation_ru="Правило", exercises=[{"ru": "Я", "en": "I am"}])],
        TalkTurn=[TalkTurn(transcript="x", reply="ok")], TalkSummary=[TalkSummary()]))
    await make_user(env, current_topic="to_be")
    await env.send("/lesson")
    await env.send(data="ls:go")
    await env.send("I am")
    assert (await env.repo.get_or_create_user(UID))["current_topic"] == "to_be_neg_q"
    assert "Тема пройдена" in env.texts()


async def test_talk_interests_why_and_goal(env):
    turn = TalkTurn(transcript="I fine", is_correct=False,
                    corrections=[Correction(wrong="I fine", right="I am fine", explanation="Нужен am.")], reply="Nice.")
    gem = FakeGemini(TalkTurn=[turn], TalkSummary=[TalkSummary()])
    gem.texts = ["Чтобы связать подлежащее и прилагательное, нужен глагол to be."]
    set_gemini(env, gem)
    await make_user(env, interests="Футбол и спорт", daily_goal=2)
    await env.send("/talk")
    await env.send(data="sc:interests")
    await env.send("I fine")
    assert "Дневная цель выполнена" in env.texts()  # 2 очка за реплику
    await env.send(data="why:0")
    assert "to be" in env.texts()
    await env.send(data="t:end")
    assert "Итоги разговора" in env.texts()


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
    await env.send(data="st:g:40")
    await env.send(data="st:o:teacher")
    await env.send(data="st:ru")
    user = await env.repo.get_or_create_user(UID)
    assert (user["daily_goal"], user["partner_role"], user["ru_help"]) == (40, "teacher", 0)
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
    await make_user(env, current_topic="to_be")
    await env.send("/test")
    await env.send("I am a student")
    await env.send(data="ts:idk")
    assert "Результат: 1/2" in env.texts()
    assert (await env.repo.get_or_create_user(UID))["last_test"]


async def test_voice_forbidden_falls_back_to_audio(env):
    from aiogram.exceptions import TelegramBadRequest

    original = env.session.make_request

    async def forbidden(bot, method, timeout=None):
        if isinstance(method, SendVoice):
            raise TelegramBadRequest(method=method, message="Bad Request: VOICE_MESSAGES_FORBIDDEN")
        return await original(bot, method, timeout)

    env.session.make_request = forbidden
    await env.send("/talk")
    await env.send(data="sc:intro")
    assert any(kind == "SendAudio" for kind, _ in env.session.sent)


async def test_progress_and_level(env):
    await make_user(env, current_topic="to_be", nick="Анна")
    await env.repo.add_activity(UID, 30, 1)
    await env.send("/progress")
    assert "Ваш прогресс" in env.texts() and "Серия" in env.texts()
    await env.send("/level")
    await env.send(data="lp:0")
    await env.send(data="lt:comparatives")
    user = await env.repo.get_or_create_user(UID)
    assert (user["current_topic"], user["level"]) == ("comparatives", "A2")
    await env.send(data="lv:test")
    for i, q in enumerate(curriculum.load_placement(include_a2=True)):
        await env.send(data=f"lq:{i}:{q['answer']}")
    user = await env.repo.get_or_create_user(UID)
    assert (user["current_topic"], user["level"]) == ("future_forms", "A2")
    await env.send(data="lt:alphabet")
    assert (await env.repo.get_or_create_user(UID))["level"] == "A1"


async def test_weak_spots(env):
    set_gemini(env, FakeGemini(PracticeSet=[PracticeSet(exercises=[
        {"ru": "Я студент", "en": "I am a student"}, {"ru": "Он врач", "en": "He is a doctor"}])],
        AnswerCheck=[AnswerCheck(correct=False)]))
    await make_user(env)
    await env.send("/weak")
    assert "пока нет" in env.texts().lower()
    for _ in range(2):
        await env.repo.add_mistake(UID, "I student", "I am a student", "Нужен am.")
    await env.send("/weak")
    assert "×2" in env.texts()
    await env.send(data="wk:start")
    await env.send("I am a student")
    await env.send(data="wk:idk")
    assert "Результат: 1/2" in env.texts()


async def test_repeat_after_me(env):
    set_gemini(env, FakeGemini(PronunciationCheck=[PronunciationCheck(
        transcript="hello my name is anna", score=4, issues=["th звучит как s"], tip="Язык между зубами")]))
    await make_user(env)
    await env.send("/repeat")
    assert any(kind == "SendVoice" for kind, _ in env.session.sent)
    await env.send(voice=True)
    assert "4/5" in env.texts() and "Язык между зубами" in env.texts()
    await env.send(data="pr:slow")
    await env.send(data="pr:next")
    await env.send(data="pr:stop")
    assert await env.state().get_state() is None


async def test_listening(env):
    qs = [ListenQuestion(q="Where is Tom?", options=["Home", "Park", "Shop"], answer=0),
          ListenQuestion(q="What does he eat?", options=["Pizza", "Rice", "Soup"], answer=1)]
    set_gemini(env, FakeGemini(ListenSet=[ListenSet(story="Tom is at home. He eats rice.", questions=qs)]))
    await make_user(env, interests="Готовка")
    await env.send("/listen")
    await env.send(data="lis:text")
    assert "Tom is at home" in env.texts()
    await env.send(data="lis:go")
    await env.send(data="lia:0:0")
    await env.send(data="lia:1:0")
    assert "Результат: 1/2" in env.texts()


async def test_translate(env):
    set_gemini(env, FakeGemini(TranslateResult=[TranslateResult(
        source_text="Привет", source_lang="ru", target_text="Hello", note="")]))
    await make_user(env)
    await env.send("/translate Привет")
    assert any(kind == "SendVoice" and "Hello" in text for kind, text in env.session.sent)
    await env.send(data="tr:add")
    assert (await env.repo.find_word(UID, "hello"))["translation"] == "Привет"
    await env.send("/translate")
    await env.send(voice=True)


async def test_vocab_tools(env):
    set_gemini(env, FakeGemini(WordInfo=[WordInfo(word="dog", translation="собака", example="A dog.")]))
    await make_user(env)
    await env.send("/add apple яблоко")
    assert (await env.repo.find_word(UID, "apple"))["translation"] == "яблоко"
    await env.send("/add собака")                 # без пары: перевод и пример от ИИ
    assert (await env.repo.find_word(UID, "dog"))["example"] == "A dog."
    await env.send("/due apple")
    await env.send("/export")
    assert any(kind == "SendDocument" for kind, _ in env.session.sent)
    await env.send("/import")
    await env.send("cat;кот;A cat.")
    assert (await env.repo.find_word(UID, "cat"))["translation"] == "кот"


async def test_reset(env):
    await make_user(env, nick="Анна", current_topic="articles")
    await env.repo.add_word(UID, "dog", "собака")
    await env.repo.add_mistake(UID, "a", "b", "c")
    await env.send("/reset")
    await env.send(data="rs:words")
    await env.send(data="rc:words")
    assert (await env.repo.word_stats(UID))["total"] == 0
    await env.send(data="rc:progress")
    user = await env.repo.get_or_create_user(UID)
    assert user["current_topic"] == "alphabet" and await env.repo.mistake_count(UID) == 0
    await env.send(data="rc:profile")
    assert (await env.repo.get_or_create_user(UID))["nick"] is None
    await env.send(data="rc:all")
    assert await env.repo.list_users() == []


async def test_admin_commands(env):
    await make_user(env)
    await env.send("/allow 555")
    assert await env.repo.is_allowed(555)
    await env.send("/users")
    assert "555" in env.texts()
    await env.send("/deny 555")
    assert not await env.repo.is_allowed(555)
    await env.send("/backup")
    assert any(kind == "SendDocument" for kind, _ in env.session.sent)
    env.dp["config"] = replace(env.dp["config"], allowed_user_ids=(999,))
    await env.send("/allow 777")
    assert "только для администратора" in env.texts() and not await env.repo.is_allowed(777)
