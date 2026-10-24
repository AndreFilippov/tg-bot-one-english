from functools import lru_cache

import yaml

from config import DATA_DIR


LEVELS = (("A1", "curriculum_a1.yaml"), ("A2", "curriculum_a2.yaml"))


@lru_cache
def load_topics() -> list[dict]:
    """Все темы по порядку: сначала A1, затем A2. У каждой темы есть поле level."""
    topics = []
    for level, filename in LEVELS:
        path = DATA_DIR / filename
        if path.exists():
            with open(path, encoding="utf-8") as f:
                topics += [{**t, "level": level} for t in yaml.safe_load(f)["topics"]]
    return topics


def topic_by_id(topic_id: str) -> dict:
    topics = load_topics()
    return next((t for t in topics if t["id"] == topic_id), topics[0])


@lru_cache
def load_scenarios() -> dict[str, dict]:
    with open(DATA_DIR / "scenarios.yaml", encoding="utf-8") as f:
        return {s["id"]: s for s in yaml.safe_load(f)["scenarios"]}


def next_topic_id(topic_id: str) -> str | None:
    ids = [t["id"] for t in load_topics()]
    i = ids.index(topic_id) if topic_id in ids else -1
    return ids[i + 1] if 0 <= i + 1 < len(ids) else None


@lru_cache
def _placement_all() -> list[dict]:
    with open(DATA_DIR / "placement_test.yaml", encoding="utf-8") as f:
        return [{"level": "A1", **q} for q in yaml.safe_load(f)["questions"]]


def load_placement(include_a2: bool = False) -> list[dict]:
    return [q for q in _placement_all() if include_a2 or q["level"] == "A1"]


def topic_number(topic_id: str) -> tuple[int, int]:
    """(номер темы, всего тем) в общей программе."""
    ids = [t["id"] for t in load_topics()]
    return (ids.index(topic_id) + 1 if topic_id in ids else 1), len(ids)


@lru_cache
def load_pronunciation() -> list[dict]:
    with open(DATA_DIR / "pronunciation.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["phrases"]


INTEREST_TAGS = ["Путешествия", "Футбол и спорт", "Кино и сериалы", "Музыка", "IT и компьютеры", "Готовка",
                 "Животные", "Книги", "Игры", "Машины", "Работа и бизнес", "Природа"]


def start_topic_for(questions: list[dict], first_fail: str | None) -> str:
    """Тема, с которой начать по результатам теста уровня."""
    if first_fail:
        return first_fail
    last = questions[-1]["topic"]
    return next_topic_id(last) or last
