import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "data" / "questions.json"
_DATA = json.loads(_PATH.read_text(encoding="utf-8"))["topics"]


def list_topics() -> list[str]:
    return list(_DATA.keys())


def _match_topic(text: str) -> str | None:
    t = text.lower().strip()
    for key, info in _DATA.items():
        if key.replace("_", " ") in t or t in key.replace("_", " "):
            return key
        if any(kw in t for kw in info["keywords"]):
            return key
    return None


def pick_next(topic: str, asked_ids: set[str]) -> tuple[str | None, dict | None]:
    """Returns (matched_topic, question). question is None if the topic is
    unknown or all its questions were already asked."""
    key = _match_topic(topic)
    if key is None:
        return None, None
    for q in _DATA[key]["questions"]:
        if q["id"] not in asked_ids:
            return key, q
    return key, None