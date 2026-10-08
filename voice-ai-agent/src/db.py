import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mentor.db"

PROFILE_FIELDS = [
    "name", "hometown", "education", "optional_subject",
    "hobbies", "work_experience", "service_preference", "medium",
]
DIMENSIONS = ["clarity", "depth", "balance", "awareness", "authenticity", "composure"]
INTENSITIES = {"gentle", "standard", "tough"}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), "
            + ", ".join(f"{f} TEXT" for f in PROFILE_FIELDS)
            + ")"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS interviews ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, intensity TEXT, "
            + ", ".join(f"{d} INTEGER" for d in DIMENSIONS)
            + ", overall REAL, weakest TEXT, topics TEXT, summary TEXT)"
        )
        conn.commit()


def get_profile() -> dict:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if not row:
        return {}
    return {f: row[f] for f in PROFILE_FIELDS if row[f]}


def save_profile(fields: dict) -> None:
    """Merge new non-empty fields into the saved profile."""
    current = get_profile()
    for k, v in fields.items():
        if k in PROFILE_FIELDS and v and v.strip():
            current[k] = v.strip()
    cols = ", ".join(PROFILE_FIELDS)
    marks = ", ".join("?" for _ in PROFILE_FIELDS)
    with closing(_connect()) as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO profile (id, {cols}) VALUES (1, {marks})",
            [current.get(f) for f in PROFILE_FIELDS],
        )
        conn.commit()


def save_interview(intensity: str, scores: dict, topics: str, summary: str):
    overall = round(sum(scores[d] for d in DIMENSIONS) / len(DIMENSIONS), 1)
    weakest = min(DIMENSIONS, key=lambda d: scores[d])
    cols = ", ".join(DIMENSIONS)
    marks = ", ".join("?" for _ in DIMENSIONS)
    with closing(_connect()) as conn:
        conn.execute(
            f"INSERT INTO interviews (intensity, {cols}, overall, weakest, topics, summary) "
            f"VALUES (?, {marks}, ?, ?, ?, ?)",
            [intensity, *[scores[d] for d in DIMENSIONS], overall, weakest, topics, summary],
        )
        conn.commit()
    return overall, weakest


def recent_interviews(limit: int = 3) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT overall, weakest, topics, intensity, created_at "
            "FROM interviews ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def weakest_dimension(window: int = 5) -> str | None:
    avgs = ", ".join(f"AVG({d}) AS {d}" for d in DIMENSIONS)
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {avgs} FROM (SELECT * FROM interviews ORDER BY id DESC LIMIT ?)",
            (window,),
        ).fetchone()
    vals = {d: row[d] for d in DIMENSIONS if row[d] is not None}
    return min(vals, key=vals.get) if vals else None


init_db()