import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import db
from evaluator import evaluate
from prompts import build_instructions
from session_log import attach_logging, history_to_turns

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


# ============================================================
# CONFIG
# ============================================================

load_dotenv(".env.local")

logger = logging.getLogger("upsc-board")

EVALS_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "evals"
)


# ============================================================
# ASSISTANT
# ============================================================

class Assistant(Agent):
    def __init__(self) -> None:

        super().__init__(
            # Keep this because your current AgentSession
            # does not configure an LLM separately.
            llm=inference.LLM(
                model="google/gemma-4-31b-it"
            ),

            instructions=build_instructions(
                db.get_profile(),
                db.recent_interviews(),
                db.weakest_dimension(),
            ),
        )

        self.session_id = uuid.uuid4().hex[:8]

    # ========================================================
    # SAVE PROFILE
    # ========================================================

    @function_tool
    async def save_profile(
        self,
        context: RunContext,
        name: str = "",
        hometown: str = "",
        education: str = "",
        optional_subject: str = "",
        hobbies: str = "",
        work_experience: str = "",
        service_preference: str = "",
        medium: str = "",
    ) -> str:
        """Save the candidate's background details so they do not have to repeat them next time.
        Fill only the fields the candidate has actually shared.

        Args:
            name: Candidate's name.
            hometown: Hometown, district or home state.
            education: Graduation subject and college.
            optional_subject: UPSC optional subject, if any.
            hobbies: Hobbies and interests.
            work_experience: Work experience, if any.
            service_preference: Preferred services, for example IAS or IFS.
            medium: Preferred interview language, English or Hindi.
        """

        fields = dict(
            name=name,
            hometown=hometown,
            education=education,
            optional_subject=optional_subject,
            hobbies=hobbies,
            work_experience=work_experience,
            service_preference=service_preference,
            medium=medium,
        )

        await asyncio.to_thread(
            db.save_profile,
            fields,
        )

        return "Saved."

    # ========================================================
    # FINISH INTERVIEW
    # ========================================================

    @function_tool
    async def finish_interview(
        self,
        context: RunContext,
        intensity: str,
    ) -> str:
        """Evaluate and save the interview. Call once at the end, after telling the candidate
        the board needs a moment to deliberate.

        Args:
            intensity: gentle, standard or tough.
        """

        # ----------------------------------------------------
        # Get current session
        # ----------------------------------------------------

        session = (
            getattr(context, "session", None)
            or self.session
        )

        # ----------------------------------------------------
        # Extract conversation history
        # ----------------------------------------------------

        turns, _ = history_to_turns(
            session.history.to_dict()
        )

        # ----------------------------------------------------
        # Evaluate interview
        # ----------------------------------------------------

        try:
            result = await evaluate(turns)

        except Exception:
            logger.exception(
                "evaluation failed"
            )

            return (
                "Evaluation failed. "
                "Give brief qualitative feedback only "
                "and do not mention any scores."
            )

        # ----------------------------------------------------
        # Check whether there were enough answers
        # ----------------------------------------------------

        if result.get("too_short"):
            return (
                "Too few answers to evaluate. "
                "Tell the candidate you need a few more answers "
                "and continue the interview."
            )

        # ----------------------------------------------------
        # Normalize intensity
        # ----------------------------------------------------

        intensity = intensity.lower().strip()

        if intensity not in db.INTENSITIES:
            intensity = "standard"

        # ----------------------------------------------------
        # Save interview to database
        # ----------------------------------------------------

        overall, weakest = await asyncio.to_thread(
            db.save_interview,
            intensity,
            result["scores"],
            ", ".join(result["topics"]),
            result["summary"],
        )

        # ----------------------------------------------------
        # Save detailed evaluation JSON
        # ----------------------------------------------------

        EVALS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        record = {
            "created_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "intensity": intensity,
            "overall": overall,
            "weakest": weakest,
            **result,
        }

        eval_path = (
            EVALS_DIR
            / f"{self.session_id}.json"
        )

        eval_path.write_text(
            json.dumps(
                record,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        logger.info(
            "Interview evaluation saved: %s",
            eval_path,
        )

        # ----------------------------------------------------
        # Format factual slips
        # ----------------------------------------------------

        slips = "; ".join(
            f"{s.get('claim', '')} -> "
            f"{s.get('correction', '')}"
            for s in result["factual_slips"]
        ) or "none"

        # ----------------------------------------------------
        # Return evaluation to LLM
        # ----------------------------------------------------

        return (
            f"EVALUATION SAVED. "
            f"Overall {overall} out of 10. "
            f"Weakest area: {weakest}. "
            f"Strengths: {'; '.join(result['strengths'])}. "
            f"Improvements: {'; '.join(result['improvements'])}. "
            f"Factual slips: {slips}."
        )


# ============================================================
# LIVEKIT SERVER
# ============================================================

server = AgentServer()


# ============================================================
# VOICE SESSION
# ============================================================

@server.rtc_session(
    agent_name="voice-ai-agent"
)
async def my_agent(ctx: JobContext):

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    logger.info(
        "Starting UPSC interview in room: %s",
        ctx.room.name,
    )

    # ========================================================
    # AGENT SESSION
    # ========================================================

    session = AgentSession(

        # ----------------------------------------------------
        # SARVAM STT
        # ----------------------------------------------------

        stt=sarvam.STT(
            language="hi-IN",
            model="saaras:v4",
            mode="codemix",
            sample_rate=16000,
            high_vad_sensitivity=True,
        ),

        # ----------------------------------------------------
        # STT CONTEXT
        # ----------------------------------------------------

        stt_context_options=STTContextOptions(
            keyterms=[
                "LiveKit",
                "UPSC",
                "IAS",
                "IPS",
                "IFS",
                "DAF",
                "Python",
                "Java",
                "JavaScript",
                "React",
                "machine learning",
                "artificial intelligence",
                "algorithms",
                "data structures",
                "civil services",
                "fundamental rights",
                "Article 21",
                "Parliament",
                "Supreme Court",
                "fiscal deficit",
                "GDP",
                "inflation",
                "governance",
                "democracy",
                "federalism",
                "constitution",
            ],
            keyterm_detection={
                "enabled": True,
            },
        ),

        # ----------------------------------------------------
        # SARVAM TTS
        # ----------------------------------------------------

        tts=sarvam.TTS(
            target_language_code="hi-IN",
            model="bulbul:v3",
            speaker="shubh",
            speech_sample_rate=22050,
            pace=1.0,
        ),

        # ----------------------------------------------------
        # TURN DETECTION
        # ----------------------------------------------------

        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),

            interruption={
                "mode": "adaptive",
            },

            preemptive_generation={
                "enabled": True,
            },
        ),

        # ----------------------------------------------------
        # EXPRESSIVE VOICE
        # ----------------------------------------------------

        expressive=True,
    )

    # ========================================================
    # CREATE ASSISTANT
    # ========================================================

    assistant = Assistant()

    # ========================================================
    # START SESSION
    # ========================================================

    await session.start(
        agent=assistant,
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

    # ========================================================
    # ATTACH SESSION LOGGING
    # ========================================================

    attach_logging(
        ctx,
        session,
        assistant.session_id,
    )

    # ========================================================
    # CONNECT
    # ========================================================

    await ctx.connect()

    logger.info(
        "Connected to LiveKit room: %s",
        ctx.room.name,
    )

    # ========================================================
    # INITIAL GREETING
    # ========================================================

    await session.generate_reply(
        instructions=(
            "Greet the candidate in one or two short sentences "
            "as the chairperson of the mock UPSC interview board, "
            "then follow your setup steps."
        )
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    cli.run_app(server)