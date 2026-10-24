from functools import lru_cache

import yaml

from config import DATA_DIR


@lru_cache
def load_topics() -> list[dict]:
    with open(DATA_DIR / "curriculum_a1.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["topics"]


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
def load_placement() -> list[dict]:
    with open(DATA_DIR / "placement_test.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]
