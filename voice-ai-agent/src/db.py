import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mentor.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(_connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                topic TEXT,
                question_id TEXT,
                question TEXT NOT NULL,
                score INTEGER NOT NULL,
                feedback TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def save_score(session_id, topic, question_id, question, score, feedback) -> None:
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO scores (session_id, topic, question_id, question, score, feedback) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, topic, question_id, question, score, feedback),
        )
        conn.commit()


def session_summary(session_id: str) -> dict:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(score) AS avg FROM scores WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return {"answered": row["n"], "average": round(row["avg"], 1) if row["avg"] is not None else None}


init_db()