import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env.local")

from evaluator import evaluate  # noqa: E402
from prompts import build_instructions  # noqa: E402
from session_log import TRANSCRIPT_DIR  # noqa: E402

N_BOARD_TURNS = 9
CANDIDATE_MODEL = os.getenv("SIM_CANDIDATE_MODEL", "claude-haiku-5-5")

PROFILE = {
    "name": "Aarav", "hometown": "Indore, Madhya Pradesh",
    "education": "BTech Computer Science", "optional_subject": "Public Administration",
    "hobbies": "chess, long-distance running, reading history",
    "work_experience": "2 years as a software engineer",
    "service_preference": "IAS, IFS", "medium": "English",
}

PERSONAS = {
    "strong": "You are well prepared. You answer in a structured way with concrete examples, see multiple sides of issues, and honestly admit when you are unsure.",
    "vague": "You give generic, vague answers full of buzzwords like 'holistic' and 'stakeholders', with no examples and no real depth.",
    "bluffer": "You sound confident but state several wrong facts, and when you do not know something you bluff instead of admitting it.",
    "one_sided": "You hold strong extreme opinions and refuse to acknowledge the other side of any issue.",
}

SIM_NOTE = (
    "\n\nSIMULATION NOTE: No tools exist in this test. Never call or mention tools. "
    "Skip the final evaluation step and simply close the interview politely after about 8 questions."
)


async def call(client, model, system, messages, max_tokens=300) -> str:
    r = await client.messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=messages
    )
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()


async def run_one(client, model, persona, sem) -> dict:
    async with sem:
        board_system = build_instructions(PROFILE, [], None) + SIM_NOTE
        cand_system = (
            f"You are role-playing a UPSC aspirant in a mock interview. Profile: {json.dumps(PROFILE)}. "
            f"Behaviour: {PERSONAS[persona]} Reply in 1 to 4 spoken sentences in natural Indian English "
            "with occasional Hindi words. Never mention that you are an AI or role-playing."
        )
        opener = "Hello, I am ready. My details are correct, standard intensity please. Let's begin."
        board_msgs = [{"role": "user", "content": opener}]
        cand_msgs: list[dict] = []
        turns = [{"role": "user", "text": opener}]
        for i in range(N_BOARD_TURNS):
            board = await call(client, model, board_system, board_msgs)
            board_msgs.append({"role": "assistant", "content": board})
            turns.append({"role": "assistant", "text": board})
            if i == N_BOARD_TURNS - 1:
                break
            cand_msgs.append({"role": "user", "content": board})
            cand = await call(client, CANDIDATE_MODEL, cand_system, cand_msgs, 250)
            cand_msgs.append({"role": "assistant", "content": cand})
            board_msgs.append({"role": "user", "content": cand})
            turns.append({"role": "user", "text": cand})
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", f"sim-{model}-{persona}".lower())
        (TRANSCRIPT_DIR / f"{slug}.json").write_text(
            json.dumps({
                "session_id": slug, "source": f"sim:{model}:{persona}",
                "turns": turns, "tool_calls": [], "latency": {},
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        result = await evaluate(turns)
        overall = round(sum(result["scores"].values()) / 6, 1) if not result.get("too_short") else None
        print(f"done: {model:20} {persona:10} evaluator overall = {overall}")
        return {"model": model, "persona": persona, "overall": overall}


async def main(models: list[str]) -> None:
    client = AsyncAnthropic()
    sem = asyncio.Semaphore(4)
    jobs = [run_one(client, m, p, sem) for m in models for p in PERSONAS]
    rows = await asyncio.gather(*jobs)
    print("\nEvaluator validity check (should rank strong > others):")
    for p in PERSONAS:
        vals = [r["overall"] for r in rows if r["persona"] == p and r["overall"] is not None]
        print(f"  {p:10} mean overall = {sum(vals) / len(vals):.1f}" if vals else f"  {p:10} n/a")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["claude-haiku-5-5", "claude-sonnet-5-5"])
    asyncio.run(main(ap.parse_args().models))