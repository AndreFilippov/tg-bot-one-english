"""Ежедневный урок: повторение слов -> грамматика -> 5 фраз на перевод -> голосовой мини-диалог."""
import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import Config
from db.repo import Repo
from handlers import review, talk
from handlers.helpers import build_system, error_text, get_user, say, track
from services import curriculum
from services.exercises import check_translation
from services.gemini import GeminiService
from services.models import AnswerCheck, LessonContent
from services.prompts import render
from services.tts import TTSService

log = logging.getLogger(__name__)
router = Router()

PASS_RATIO = 0.8  # переход к следующей теме при 80%+ правильных ответов


class Lesson(StatesGroup):
    intro = State()
    exercise = State()


def exercise_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🤷 Не знаю", callback_data="ls:idk")]])


def local_hint(expected: str) -> str:
    return f"Подсказка: ответ начинается со слова «{expected.split()[0]}»."


@router.message(Command("lesson"))
async def cmd_lesson(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                     config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await state.clear()
    topic = curriculum.topic_by_id(user["current_topic"])
    await message.answer(f"📚 <b>Урок на сегодня</b>\nТема: <b>{html.escape(topic['title'])}</b>\n\n"
                         "План: 1) повторение слов 2) грамматика 3) 5 фраз на перевод 4) мини-диалог голосом.")
    lesson = {"topic_id": topic["id"]}
    await review.start_review(message, state, repo, gemini, tts, user, flow={"lesson": lesson}, limit=5)


async def step_grammar(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                       user: dict, lesson: dict) -> None:
    topic = curriculum.topic_by_id(lesson["topic_id"])
    await message.answer(f"📖 <b>Грамматика: {html.escape(topic['title'])}</b>\n⏳ Готовлю объяснение…")
    try:
        prompt = render("lesson_content", topic_title=topic["title"], topic_focus=topic["focus"],
                        words=", ".join(await repo.sample_words(user["user_id"])) or "none yet")
        content = await gemini.generate_json(LessonContent, prompt, await build_system(repo, user, topic["id"]))
        if not content.exercises:
            raise ValueError("no exercises")
    except Exception as e:
        log.exception("lesson content failed")
        await state.clear()
        await message.answer(error_text(e) + "\nЗапустите /lesson ещё раз.")
        return

    await message.answer(html.escape(content.explanation_ru))
    for ex in content.examples:
        caption = f"{html.escape(ex.en)}\n🇷🇺 {html.escape(ex.ru)}"
        try:
            await say(message, tts, user, ex.en, caption_prefix=caption, show_text=False)
        except Exception:
            log.exception("example tts failed")
            await message.answer(caption)
    await state.set_state(Lesson.intro)
    await state.update_data(lesson={**lesson, "exercises": [e.model_dump() for e in content.exercises],
                                    "idx": 0, "correct": 0, "attempt": 1})
    await message.answer("Готовы к упражнениям?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ К упражнениям", callback_data="ls:go")]]))


@router.callback_query(Lesson.intro, F.data == "ls:go")
async def on_go(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.set_state(Lesson.exercise)
    await send_exercise(cb.message, (await state.get_data())["lesson"])


async def send_exercise(message: Message, lesson: dict) -> None:
    ex = lesson["exercises"][lesson["idx"]]
    await message.answer(f"✍️ <b>Упражнение {lesson['idx'] + 1}/{len(lesson['exercises'])}</b>\n"
                         f"Переведите на английский:\n<b>{html.escape(ex['ru'])}</b>", reply_markup=exercise_kb())


async def process_answer(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                         user: dict, answer: str) -> None:
    lesson = (await state.get_data())["lesson"]
    ex = lesson["exercises"][lesson["idx"]]
    attempt = lesson["attempt"]
    if answer:
        try:
            topic = curriculum.topic_by_id(lesson["topic_id"])["title"]
            check = await check_translation(gemini, await build_system(repo, user, lesson["topic_id"]), topic,
                                            ex["ru"], ex["en"], answer, attempt)
        except Exception as e:
            log.exception("answer check failed")
            await message.answer(error_text(e) + "\nОтправьте ответ ещё раз.")
            return
    else:
        check = AnswerCheck(correct=False)
    await track(repo, message, user["user_id"], 1)

    if check.correct:
        lesson["correct"] += attempt == 1
        await message.answer("✅ Верно!" if attempt == 1 else "✅ Верно, уже с подсказкой.")
    elif attempt == 1:
        lesson["attempt"] = 2
        await state.update_data(lesson=lesson)
        await message.answer(f"❌ Пока нет.\n💡 {html.escape(check.hint) if check.hint else local_hint(ex['en'])}\n"
                             "Попробуйте ещё раз.", reply_markup=exercise_kb())
        return
    else:
        why = f"\n{html.escape(check.explanation)}" if check.explanation else ""
        await message.answer(f"Правильный ответ: <b>{html.escape(ex['en'])}</b>{why}")
        await repo.add_mistake(user["user_id"], answer or "(не знаю)", ex["en"], check.explanation,
                               type_=f"lesson:{lesson['topic_id']}")

    lesson["idx"] += 1
    lesson["attempt"] = 1
    if lesson["idx"] < len(lesson["exercises"]):
        await state.update_data(lesson=lesson)
        await send_exercise(message, lesson)
        return
    await finish_exercises(message, state, repo, gemini, tts, user, lesson)


@router.message(Lesson.exercise, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                  config: Config) -> None:
    user = await get_user(repo, message.from_user, config)
    await process_answer(message, state, repo, gemini, tts, user, message.text)


@router.message(Lesson.exercise, F.voice)
async def on_voice(message: Message) -> None:
    await message.answer("В упражнениях ответ пишется текстом. Голосом мы поговорим в мини-диалоге.")


@router.callback_query(Lesson.exercise, F.data == "ls:idk")
async def on_idk(cb: CallbackQuery, state: FSMContext, repo: Repo, gemini: GeminiService, tts: TTSService,
                 config: Config) -> None:
    await cb.answer()
    user = await get_user(repo, cb.from_user, config)
    await process_answer(cb.message, state, repo, gemini, tts, user, "")


async def finish_exercises(message: Message, state: FSMContext, repo: Repo, gemini: GeminiService,
                           tts: TTSService, user: dict, lesson: dict) -> None:
    total, correct = len(lesson["exercises"]), lesson["correct"]
    topic_id = lesson["topic_id"]
    await repo.add_topic_result(user["user_id"], topic_id, correct, total)
    passed = correct / total >= PASS_RATIO
    next_id = None
    if passed:
        await repo.set_topic_status(user["user_id"], topic_id, "done")
        next_id = curriculum.next_topic_id(topic_id)
        if next_id:
            await repo.update_user(user["user_id"], current_topic=next_id)
        result = f"🎉 Тема пройдена! Результат {correct}/{total}."
    else:
        result = (f"Результат {correct}/{total}. Для перехода к следующей теме нужно не меньше "
                  f"{round(PASS_RATIO * 100)}% — повторим эту тему в следующем уроке.")
    await message.answer(result)

    topic = curriculum.topic_by_id(topic_id)
    scenario = {"id": f"lesson:{topic_id}", "emoji": "🎙", "title": "Мини-диалог по теме",
                "goal": f"Short practice dialog. Ask the student simple questions that need the grammar topic "
                        f"'{topic['title']}' ({topic['focus']}) in their answers. Everyday situation of your choice."}
    await state.clear()
    info = {"topic_id": topic_id, "correct": correct, "total": total, "passed": passed, "next_id": next_id}
    await talk.begin_talk(message, state, repo, gemini, tts, user, scenario, topic_id=topic_id,
                          extra={"lesson": info}, max_turns=3)


async def finish_lesson(message: Message, repo: Repo, user: dict, lesson: dict) -> None:
    await track(repo, message, user["user_id"], points=5, lessons=1)
    stats = await repo.word_stats(user["user_id"])
    lines = ["✅ <b>Урок завершён!</b>", f"Упражнения: {lesson['correct']}/{lesson['total']}"]
    if lesson["passed"] and lesson.get("next_id"):
        lines.append(f"Следующая тема: <b>{html.escape(curriculum.topic_by_id(lesson['next_id'])['title'])}</b>")
    elif lesson["passed"]:
        lines.append("Вы прошли всю программу A1! 🎓")
    lines.append(f"Слов в словаре: {stats['total']}, на повторение: {stats['due']}")
    lines.append("\n/lesson — следующий урок, /words — словарь, /talk — свободный разговор")
    await message.answer("\n".join(lines))
