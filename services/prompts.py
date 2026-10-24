import re
from functools import lru_cache

from config import PROMPTS_DIR


@lru_cache
def _read(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def render(name: str, **values) -> str:
    """Подставляет {{key}} в prompts/<name>.txt."""
    text = _read(name)
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values.get(m.group(1), "")), text)
