import json
import os

from anthropic import AsyncAnthropic

DIMENSIONS = ["clarity", "depth", "balance", "awareness", "authenticity", "composure"]
DEFAULT_MODEL = os.getenv("EVALUATOR_MODEL", "claude-sonnet-5-5")
MIN_CANDIDATE_TURNS = 3

SYSTEM = """You are a senior, strict evaluator of UPSC Civil Services Personality Test (interview) performances.
You receive the transcript of a mock interview between a BOARD (an AI chairperson) and a CANDIDATE.
The transcript comes from speech recognition of Indian-accented English/Hinglish. Ignore minor transcription errors and odd spellings. Judge substance only. Hindi may appear in Roman or Devanagari script.

Score the CANDIDATE on six dimensions, each an integer from 0 to 10:
- clarity: structured, to-the-point answers
- depth: analytical depth beyond surface facts
- balance: sees multiple sides, avoids one-sided or extreme views
- awareness: knowledge of own background, state, current issues and governance
- authenticity: honest, genuine, not memorised or bluffing; admits uncertainty
- composure: calm and confident under cross-questioning

Calibration: 0-3 weak, 4-5 below average, 6-7 solid, 8-9 excellent, 10 exceptional. Most real candidates land between 4 and 7. Do not inflate scores. Vague, generic or buzzword answers without examples must score low on depth. Bluffing or confidently wrong facts must score low on authenticity.

Only report a factual slip if you are highly confident the candidate stated something wrong. Quote it briefly and give the correction. If unsure, leave it out.

Return ONLY a JSON object, no other text, in exactly this shape:
{"scores": {"clarity": 0, "depth": 0, "balance": 0, "awareness": 0, "authenticity": 0, "composure": 0},
 "summary": "one or two sentences",
 "strengths": ["short point", "short point"],
 "improvements": ["short actionable point", "short actionable point"],
 "factual_slips": [{"claim": "what they said", "correction": "what is correct"}],
 "topics": ["topic", "topic"]}"""


def format_transcript(turns: list[dict]) -> str:
    return "\n".join(
        f"{'BOARD' if t['role'] == 'assistant' else 'CANDIDATE'}: {t['text']}" for t in turns
    )


def extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[start : end + 1])


def _text_from(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


async def evaluate(turns: list[dict], model: str | None = None) -> dict:
    if sum(1 for t in turns if t["role"] == "user") < MIN_CANDIDATE_TURNS:
        return {"too_short": True}
    client = AsyncAnthropic()
    prompt = "Transcript:\n\n" + format_transcript(turns)
    last_err = None
    for _ in range(2):
        resp = await client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            data = extract_json(_text_from(resp))
            scores = {d: max(0, min(10, int(data["scores"][d]))) for d in DIMENSIONS}
            return {
                "too_short": False,
                "scores": scores,
                "summary": str(data.get("summary", "")),
                "strengths": list(data.get("strengths", []))[:3],
                "improvements": list(data.get("improvements", []))[:3],
                "factual_slips": list(data.get("factual_slips", []))[:3],
                "topics": [str(t) for t in data.get("topics", [])][:8],
                "model": model or DEFAULT_MODEL,
            }
        except Exception as e:  # retry once on malformed output
            last_err = e
    raise RuntimeError(f"Evaluator returned invalid output: {last_err}")