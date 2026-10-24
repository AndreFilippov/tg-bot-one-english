"""Сравнение ответов ученика с эталоном без обращения к ИИ."""
import re

_APOS = str.maketrans({"’": "'", "‘": "'", "`": "'"})


def normalize(text: str) -> str:
    text = text.translate(_APOS).lower().strip()
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def distance(a: str, b: str) -> int:
    """Расстояние Левенштейна."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_exact(answer: str, expected: str) -> bool:
    return normalize(answer) == normalize(expected)


def is_close(answer: str, expected: str) -> bool:
    """Одна опечатка в слове длиннее 3 букв."""
    a, e = normalize(answer), normalize(expected)
    return len(e) > 3 and a != e and distance(a, e) <= 1
