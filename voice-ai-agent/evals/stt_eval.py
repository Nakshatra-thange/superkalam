import os
import re
import time
import unicodedata
from pathlib import Path

import httpx
import jiwer
import pandas as pd
from dotenv import load_dotenv
from sarvamai import SarvamAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")
CLIPS = ROOT / "clips"
RESULTS = ROOT / "results"
DG_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "multi")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] not in ("P", "S"))
    return re.sub(r"\s+", " ", text).strip()


def devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum("\u0900" <= c <= "\u097f" for c in letters) / len(letters)


def term_recall(terms: str, hyp: str) -> float:
    items = [t.strip() for t in str(terms).split(";") if t.strip()]
    if not items:
        return float("nan")
    h = normalize(hyp)
    h_nospace = h.replace(" ", "")
    hits = sum(1 for t in items if normalize(t) in h or normalize(t).replace(" ", "") in h_nospace)
    return hits / len(items)


def safe_wer(ref: str, hyp: str) -> float:
    ref, hyp = normalize(ref), normalize(hyp)
    if not ref:
        return float("nan")
    if not hyp:
        return 1.0
    return jiwer.wer(ref, hyp)


def make_sarvam(client, mode):
    def run(path: Path) -> str:
        with open(path, "rb") as f:
            r = client.speech_to_text.transcribe(
                file=f, model="saaras:v3", mode=mode, language_code="hi-IN"
            )
        return r.transcript
    return run


def deepgram_transcribe(path: Path) -> str:
    r = httpx.post(
        "https://api.deepgram.com/v1/listen",
        params={"model": "nova-3", "language": DG_LANGUAGE, "smart_format": "true"},
        headers={
            "Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}",
            "Content-Type": "audio/wav",
        },
        content=path.read_bytes(),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


def build_systems() -> dict:
    systems = {}
    if os.getenv("SARVAM_API_KEY"):
        client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
        for mode in ("transcribe", "codemix", "translit"):
            systems[f"sarvam_{mode}"] = make_sarvam(client, mode)
    if os.getenv("DEEPGRAM_API_KEY"):
        systems["deepgram_nova3"] = deepgram_transcribe
    return systems


def main() -> None:
    manifest = pd.read_csv(CLIPS / "manifest.csv").fillna("")
    systems = build_systems()
    print(f"Systems: {list(systems)} | Clips: {len(manifest)}")
    rows = []
    for _, clip in manifest.iterrows():
        path = CLIPS / clip["file"]
        for name, fn in systems.items():
            t0, hyp, err = time.perf_counter(), "", ""
            try:
                hyp = fn(path)
            except Exception as e:
                err = str(e)[:120]
            rows.append({
                "file": clip["file"], "speaker": clip["speaker"], "system": name,
                "latency_s": round(time.perf_counter() - t0, 2),
                "wer": safe_wer(clip["reference"], hyp) if not err else float("nan"),
                "term_recall": term_recall(clip["terms"], hyp) if not err else float("nan"),
                "devanagari_share": devanagari_share(hyp),
                "hypothesis": hyp, "error": err,
            })
            print(f"{clip['file']:12} {name:20} {hyp[:70]!r} {err}")

    RESULTS.mkdir(exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "stt_per_clip.csv", index=False)
    ok = df[df["error"] == ""]
    summary = ok.groupby("system").agg(
        clips=("file", "count"),
        term_recall=("term_recall", "mean"),
        wer=("wer", "mean"),
        median_latency_s=("latency_s", "median"),
        devanagari_share=("devanagari_share", "mean"),
    ).round(3)
    summary["errors"] = df[df["error"] != ""].groupby("system").size()
    summary = summary.fillna({"errors": 0})
    by_speaker = ok.groupby(["system", "speaker"])["term_recall"].mean().unstack().round(2)
    summary.to_csv(RESULTS / "stt_summary.csv")
    by_speaker.to_csv(RESULTS / "stt_by_speaker.csv")
    print("\n=== SUMMARY ===\n", summary, "\n\n=== TERM RECALL BY SPEAKER ===\n", by_speaker)


if __name__ == "__main__":
    main()