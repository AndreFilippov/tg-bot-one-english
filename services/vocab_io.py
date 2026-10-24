"""Разбор слов для /add и /import, экспорт словаря в CSV."""
import csv
import io
import re

LATIN = re.compile(r"[A-Za-z]")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def split_pair(text: str) -> tuple[str, str] | None:
    """'apple яблоко' / 'яблоко - apple' -> ('apple', 'яблоко'). Если пары нет, вернёт None."""
    tokens = [t for t in re.split(r"[\s\-–—=:;]+", text.strip()) if t]
    latin = [t for t in tokens if LATIN.search(t) and not CYRILLIC.search(t)]
    cyr = [t for t in tokens if CYRILLIC.search(t)]
    if latin and cyr and len(latin) + len(cyr) == len(tokens):
        return " ".join(latin), " ".join(cyr)
    return None


def parse_words(text: str) -> list[tuple[str, str, str]]:
    """CSV или строки 'word;translation;example'. Разделитель определяется сам; заголовок пропускается."""
    text = text.lstrip("﻿")
    sample = text[:2000]
    delimiter = max(",;\t", key=sample.count) if any(d in sample for d in ",;\t") else ";"
    rows = []
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        cells = [c.strip() for c in row]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            continue
        if not rows and cells[0].lower() == "word":
            continue
        rows.append((cells[0], cells[1], cells[2] if len(cells) > 2 else ""))
    return rows


def to_csv(words: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["word", "translation", "example"])
    for w in words:
        writer.writerow([w["word"], w["translation"], w["example"] or ""])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM, чтобы Excel правильно показал кириллицу
