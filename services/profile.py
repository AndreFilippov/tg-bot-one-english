"""Профиль ученика: что бот помнит о владельце, роли собеседника и язык объяснений."""
import json

ROLES = {
    "friend": ("🧑‍🤝‍🧑 Друг", "a friendly, relaxed peer who is curious about the student"),
    "teacher": ("👩‍🏫 Строгий преподаватель", "a strict but kind teacher who corrects every mistake carefully"),
    "interviewer": ("🎤 Интервьюер", "an interviewer who asks many follow-up questions about the student's life"),
    "stranger": ("🧳 Прохожий / незнакомец", "a polite stranger or local person in a real-life situation"),
}

GOALS = ["Путешествия", "Работа", "Учёба", "Переезд", "Для себя"]

PROFILE_LABELS = {"nick": "Имя", "city": "Город", "occupation": "Занятие", "goal": "Цель", "interests": "Интересы"}


def explain_lang(user: dict) -> str:
    return "Russian" if user.get("ru_help", 1) else "very simple English (no Russian)"


def role_prompt(user: dict) -> str:
    return ROLES.get(user.get("partner_role") or "friend", ROLES["friend"])[1]


def facts_of(user: dict) -> list[str]:
    try:
        return list(json.loads(user.get("facts") or "[]"))
    except ValueError:
        return []


def interests_of(user: dict) -> list[str]:
    return [t.strip() for t in (user.get("interests") or "").split(",") if t.strip()]


def profile_for_prompt(user: dict) -> str:
    """Текст профиля для системного промпта (на английском)."""
    lines = []
    if user.get("nick"):
        lines.append(f"- Call the student: {user['nick']}")
    if user.get("age"):
        lines.append(f"- Age: {user['age']}")
    if user.get("city"):
        lines.append(f"- Lives in: {user['city']}")
    if user.get("occupation"):
        lines.append(f"- Work or study: {user['occupation']}")
    if user.get("goal"):
        lines.append(f"- Goal of learning English: {user['goal']}")
    if interests_of(user):
        lines.append(f"- Interests: {', '.join(interests_of(user))}")
    for fact in facts_of(user)[-10:]:
        lines.append(f"- {fact}")
    return "\n".join(lines) or "- (nothing known yet)"


def profile_for_user(user: dict) -> str:
    """Профиль для показа ученику (по-русски, HTML-безопасные значения подставляет вызывающий код)."""
    rows = [("Имя", user.get("nick")), ("Город", user.get("city")), ("Занятие", user.get("occupation")),
            ("Цель", user.get("goal")), ("Интересы", ", ".join(interests_of(user)))]
    return "\n".join(f"{label}: {value or '—'}" for label, value in rows)
