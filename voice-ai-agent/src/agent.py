import asyncio
import logging
import threading
import uuid

from dotenv import load_dotenv

import db
import questions
import rag

from prompts import build_instructions, TOOL_RULES, RAG_RULES

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    STTContextOptions,
    TurnHandlingOptions,
    cli,
    function_tool,
    inference,
    room_io,
)

from livekit.plugins import ai_coustics
from livekit.plugins import sarvam


logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):

    def __init__(self) -> None:
        super().__init__(
            llm=inference.LLM(
                model="google/gemma-4-31b-it"
            ),
            instructions=(
                build_instructions()
                + TOOL_RULES
                + RAG_RULES
            ),
        )

        self.session_id = uuid.uuid4().hex[:8]

        self.asked_ids: set[str] = set()

        self.current: dict | None = None

        # Warm up the RAG system without blocking
        # the real-time voice pipeline.
        threading.Thread(
            target=rag.warmup,
            daemon=True,
        ).start()


    # ============================================================
    # QUIZ TOOL
    # ============================================================

    @function_tool
    async def get_next_question(
        self,
        context: RunContext,
        topic: str,
    ) -> str:
        """Get the next quiz question on a topic the student wants to practice.

        Args:
            topic: The topic name, for example "photosynthesis"
                or "newton's laws".
        """

        key, q = questions.pick_next(
            topic,
            self.asked_ids,
        )

        if key is None:
            return (
                f"Unknown topic. Available topics: "
                f"{', '.join(questions.list_topics())}."
            )

        if q is None:
            return (
                "No more questions on this topic. "
                "Wrap up using get_session_summary."
            )

        self.asked_ids.add(q["id"])

        self.current = {
            "topic": key,
            **q,
        }

        return (
            f"QUESTION (ask this aloud): {q['question']}\n"
            f"REFERENCE ANSWER (private, do not read aloud): "
            f"{q['answer']}\n"
            f"HINT (only if the student is stuck): {q['hint']}"
        )


    # ============================================================
    # SCORE TOOL
    # ============================================================

    @function_tool
    async def save_score(
        self,
        context: RunContext,
        question: str,
        score: int,
        feedback: str,
    ) -> str:
        """Save the student's score for the question they just answered.

        Args:
            question: The question that was asked.
            score: Score from 0 to 10 based on how correct
                the answer was.
            feedback: One short line of feedback for the student.
        """

        score = max(
            0,
            min(10, int(score)),
        )

        cur = self.current or {}

        db.save_score(
            self.session_id,
            cur.get("topic"),
            cur.get("id"),
            question,
            score,
            feedback,
        )

        return "Saved."


    # ============================================================
    # SESSION SUMMARY TOOL
    # ============================================================

    @function_tool
    async def get_session_summary(
        self,
        context: RunContext,
    ) -> str:
        """Get the number of questions answered and average score."""

        s = db.session_summary(
            self.session_id
        )

        return (
            f"Answered {s['answered']} questions, "
            f"average score {s['average']} out of 10."
        )


    # ============================================================
    # RAG / STUDY NOTES TOOL
    # ============================================================

    @function_tool
    async def search_notes(
        self,
        context: RunContext,
        query: str,
    ) -> str:
        """Search study notes for facts to explain a concept or check an answer.

        Args:
            query: A short search query written in English,
                even if the student spoke Hindi.
        """

        # Run RAG search in a worker thread so that
        # embedding/search does not block real-time audio.
        hits = await asyncio.to_thread(
            rag.search,
            query,
        )

        if not hits:
            return (
                "NO RELEVANT NOTES FOUND. "
                "Tell the student you are not sure, "
                "and do not guess."
            )

        return "\n\n".join(
            f"[{h['source']}] {h['text']}"
            for h in hits
        )


# ================================================================
# LIVEKIT SERVER
# ================================================================

server = AgentServer()


@server.rtc_session(agent_name="voice-ai-agent")
async def my_agent(ctx: JobContext):

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }


    # ============================================================
    # VOICE SESSION
    # ============================================================

    session = AgentSession(

        # --------------------------------------------------------
        # SPEECH TO TEXT
        # --------------------------------------------------------

        stt=sarvam.STT(
            language="hi-IN",
            model="saaras:v4",
            mode="codemix",
            sample_rate=16000,
            high_vad_sensitivity=True,
        ),


        # --------------------------------------------------------
        # STT CONTEXT
        # --------------------------------------------------------

        stt_context_options=STTContextOptions(
            keyterms=[
                "LiveKit",
                "Python",
                "Java",
                "JavaScript",
                "React",
                "machine learning",
                "artificial intelligence",
                "algorithms",
                "data structures",
            ],
            keyterm_detection={
                "enabled": True,
            },
        ),


        # --------------------------------------------------------
        # TEXT TO SPEECH
        # --------------------------------------------------------

        tts=sarvam.TTS(
            target_language_code="hi-IN",
            model="bulbul:v3",
            speaker="shubh",
            speech_sample_rate=22050,
            pace=1.0,
        ),


        # --------------------------------------------------------
        # TURN DETECTION
        # --------------------------------------------------------

        turn_handling=TurnHandlingOptions(

            turn_detection=inference.TurnDetector(),

            interruption={
                "mode": "adaptive",
            },

            preemptive_generation={
                "enabled": True,
            },
        ),

        expressive=True,
    )


    # ============================================================
    # START SESSION
    # ============================================================

    await session.start(
        agent=Assistant(),
        room=ctx.room,

        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(

                noise_cancellation=(
                    ai_coustics.audio_enhancement(
                        model=(
                            ai_coustics.EnhancerModel.QUAIL_VF_S
                        )
                    )
                ),
            ),
        ),
    )


    # ============================================================
    # CONNECT TO ROOM
    # ============================================================

    await ctx.connect()


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":
    cli.run_app(server)