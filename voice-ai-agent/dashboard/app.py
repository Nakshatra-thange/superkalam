import json
import statistics
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
EVALS, TRANSCRIPTS, RESULTS = ROOT / "data" / "evals", ROOT / "data" / "transcripts", ROOT / "results"
DIMS = ["clarity", "depth", "balance", "awareness", "authenticity", "composure"]

st.set_page_config(page_title="UPSC Interview Mentor", layout="wide")
st.title("UPSC Interview Mock: Progress Dashboard")


def load_evals() -> list[dict]:
    rows = []
    for p in sorted(EVALS.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d["session_id"] = p.stem
        rows.append(d)
    return rows


evals = load_evals()
tab1, tab2, tab3 = st.tabs(["Progress", "Interview detail", "System quality (evals)"])

with tab1:
    if not evals:
        st.info("No completed interviews yet. Run a mock interview first.")
    else:
        df = pd.DataFrame([{
            "when": e["created_at"], "intensity": e["intensity"], "overall": e["overall"],
            "weakest": e["weakest"], **e["scores"],
        } for e in evals]).sort_values("when")
        c1, c2 = st.columns(2)
        c1.metric("Interviews completed", len(df))
        c2.metric("Latest overall score", f"{df.iloc[-1]['overall']} / 10")
        st.subheader("Overall score over time")
        st.line_chart(df.set_index("when")["overall"])
        st.subheader("Average by dimension")
        st.bar_chart(df[DIMS].mean())
        st.subheader("History")
        st.dataframe(df[["when", "intensity", "overall", "weakest"]], use_container_width=True)

with tab2:
    if not evals:
        st.info("Nothing to show yet.")
    else:
        pick = st.selectbox("Interview", [e["session_id"] for e in reversed(evals)])
        e = next(x for x in evals if x["session_id"] == pick)
        left, right = st.columns([1, 1])
        with left:
            st.subheader(f"Overall {e['overall']} / 10 ({e['intensity']})")
            st.bar_chart(pd.Series(e["scores"]))
            st.write(e["summary"])
            st.markdown("**Strengths**")
            for s in e["strengths"]:
                st.write(f"- {s}")
            st.markdown("**Improve next**")
            for s in e["improvements"]:
                st.write(f"- {s}")
            if e["factual_slips"]:
                st.markdown("**Possible factual slips**")
                for s in e["factual_slips"]:
                    st.write(f"- {s.get('claim', '')} (correct: {s.get('correction', '')})")
            st.caption(f"Topics: {', '.join(e['topics'])} | Evaluator: {e.get('model', '?')}")
        with right:
            tpath = TRANSCRIPTS / f"{pick}.json"
            if tpath.exists():
                t = json.loads(tpath.read_text(encoding="utf-8"))
                lat = t.get("latency", {})
                if lat.get("llm_ttft"):
                    st.caption(
                        "Median latency (s): "
                        f"end-of-turn {statistics.median(lat.get('eou_delay', [0])):.2f}, "
                        f"LLM first token {statistics.median(lat['llm_ttft']):.2f}, "
                        f"TTS first byte {statistics.median(lat.get('tts_ttfb', [0])):.2f}"
                    )
                st.subheader("Transcript")
                for turn in t["turns"]:
                    with st.chat_message("assistant" if turn["role"] == "assistant" else "user"):
                        st.write(turn["text"])
            else:
                st.caption("Transcript file not found.")

with tab3:
    st.caption("Small-sample results from my own recordings and simulated candidates.")
    for title, fname in [
        ("STT: accuracy and latency by system", "stt_summary.csv"),
        ("STT: UPSC term recall by speaker", "stt_by_speaker.csv"),
    ]:
        p = RESULTS / fname
        if p.exists():
            st.subheader(title)
            st.dataframe(pd.read_csv(p), use_container_width=True)
    q = RESULTS / "interview_quality.csv"
    if q.exists():
        st.subheader("Board behaviour audit")
        qd = pd.read_csv(q)
        st.dataframe(qd.groupby("group").mean(numeric_only=True).round(2), use_container_width=True)
    if not any((RESULTS / f).exists() for f in ("stt_summary.csv", "interview_quality.csv")):
        st.info("Run the scripts in evals/ to populate this tab.")