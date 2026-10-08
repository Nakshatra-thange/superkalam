import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT_DIR = ROOT / "data" / "transcripts"


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    parts = []
    for c in content or []:
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, dict):
            parts.append(str(c.get("text", "")))
    return " ".join(p.strip() for p in parts if p and p.strip())


def history_to_turns(history_dict: dict) -> tuple[list[dict], list[str]]:
    """Convert LiveKit's session.history.to_dict() into simple turns and tool-call names.
    role 'assistant' = the board, role 'user' = the candidate."""
    turns, tool_calls = [], []
    for item in history_dict.get("items", []):
        kind = item.get("type")
        if kind == "message" and item.get("role") in ("user", "assistant"):
            text = _text_of(item.get("content"))
            if text:
                turns.append({"role": item["role"], "text": text})
        elif kind == "function_call":
            tool_calls.append(item.get("name", "?"))
    return turns, tool_calls


def attach_logging(ctx, session, session_id: str) -> None:
    """Call right after session.start(). Saves transcript, tool calls and latency on shutdown."""
    latency = {"eou_delay": [], "llm_ttft": [], "tts_ttfb": []}
    started = time.time()

    @session.on("metrics_collected")
    def _on_metrics(ev):
        m = getattr(ev, "metrics", None)
        if m is None:
            return
        for attr, key in (
            ("end_of_utterance_delay", "eou_delay"),
            ("ttft", "llm_ttft"),
            ("ttfb", "tts_ttfb"),
        ):
            v = getattr(m, attr, None)
            if isinstance(v, (int, float)) and v > 0:
                latency[key].append(round(float(v), 3))

    async def _write_transcript():
        turns, tool_calls = history_to_turns(session.history.to_dict())
        if not turns:
            return
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session_id,
            "source": "live",
            "duration_s": round(time.time() - started),
            "turns": turns,
            "tool_calls": tool_calls,
            "latency": latency,
        }
        (TRANSCRIPT_DIR / f"{session_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    ctx.add_shutdown_callback(_write_transcript)