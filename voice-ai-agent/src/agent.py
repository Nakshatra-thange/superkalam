import asyncio
import logging
import threading
import uuid

from dotenv import load_dotenv

import db
import questions
import rag

from prompts import build_instructions, TEACHING_RULES, history_block

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
        profile = db.topic_profile()
        super().__init__(
            instructions=build_instructions() + TEACHING_RULES + history_block(profile)
        )
        self.session_id = uuid.uuid4().hex[:8]
        self.asked_ids: set[str] = set()
        threading.Thread(target=rag.warmup, daemon=True).start()

    @function_tool
    async def save_score(
        self, context: RunContext, topic: str, question: str, score: int, feedback: str
    ) -> str:
        """Save the student's score after judging their answer.

        Args:
            topic: Short topic name in English, for example "photosynthesis" or "binary search".
            question: The question you asked.
            score: Score from 0 to 10 based on how correct the answer was.
            feedback: One short line of feedback.
        """
        score = max(0, min(10, int(score)))
        topic_key = topic.lower().strip().replace(" ", "_")
        await asyncio.to_thread(
            db.save_score, self.session_id, topic_key, None, question, score, feedback
        )
        return "Saved."

    @function_tool
    async def get_session_summary(self, context: RunContext) -> str:
        """Get how many questions the student answered this session and their average score."""
        s = await asyncio.to_thread(db.session_summary, self.session_id)
        return f"Answered {s['answered']} questions, average {s['average']} out of 10."

    @function_tool
    async def search_notes(self, context: RunContext, query: str) -> str:
        """Search the student's own uploaded study notes. Use ONLY when the student
        refers to their notes, book or syllabus.

        Args:
            query: A short search query written in ENGLISH.
        """
        hits = await asyncio.to_thread(rag.search, query)
        if not hits:
            return "The student's notes do not cover this. Answer from your own general knowledge instead."
        return "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits)

    @function_tool
    async def get_assessment_question(self, context: RunContext, topic: str) -> str:
        """Get a fixed question from the standard assessment bank. Use ONLY when the
        student asks for a formal test or exam-style round.

        Args:
            topic: The topic name, for example "photosynthesis" or "newton's laws".
        """
        key, q = questions.pick_next(topic, self.asked_ids)
        if key is None:
            return "The assessment bank has no questions on this topic. Make up your own questions instead."
        if q is None:
            return "No more assessment questions on this topic. Continue with your own questions."
        self.asked_ids.add(q["id"])
        return (
            f"QUESTION (ask this aloud): {q['question']}\n"
            f"REFERENCE ANSWER (private, never read before the student answers): {q['answer']}\n"
            f"HINT (only if stuck): {q['hint']}"
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