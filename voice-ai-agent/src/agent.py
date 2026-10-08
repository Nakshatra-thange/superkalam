import asyncio
import logging

from dotenv import load_dotenv

import db
from prompts import build_instructions

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

logger = logging.getLogger("agent")


# ============================================================
# ASSISTANT
# ============================================================

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            # IMPORTANT:
            # Keep this because your AgentSession does not currently
            # configure an LLM separately.
            llm=inference.LLM(
                model="google/gemma-4-31b-it"
            ),
            instructions=build_instructions(
                db.get_profile(),
                db.recent_interviews(),
                db.weakest_dimension(),
            ),
        )

    # ========================================================
    # SAVE CANDIDATE PROFILE
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
    # SAVE INTERVIEW RESULT
    # ========================================================

    @function_tool
    async def save_interview_result(
        self,
        context: RunContext,
        intensity: str,
        clarity: int,
        depth: int,
        balance: int,
        awareness: int,
        authenticity: int,
        composure: int,
        topics_covered: str,
        summary: str,
    ) -> str:
        """Save the evaluation at the end of the interview. Call this before giving spoken feedback.

        Args:
            intensity: gentle, standard or tough.
            clarity: Score 0 to 10 for structured, to-the-point answers.
            depth: Score 0 to 10 for analytical depth.
            balance: Score 0 to 10 for seeing multiple sides.
            awareness: Score 0 to 10 for knowledge of background, state and current issues.
            authenticity: Score 0 to 10 for honesty and not bluffing.
            composure: Score 0 to 10 for calm and confidence under cross-questioning.
            topics_covered: Short comma-separated list of topics asked about.
            summary: One or two sentences summarising performance.
        """

        intensity = intensity.lower().strip()

        if intensity not in db.INTENSITIES:
            intensity = "standard"

        scores = {
            "clarity": clarity,
            "depth": depth,
            "balance": balance,
            "awareness": awareness,
            "authenticity": authenticity,
            "composure": composure,
        }

        scores = {
            k: max(0, min(10, int(v)))
            for k, v in scores.items()
        }

        overall, weakest = await asyncio.to_thread(
            db.save_interview,
            intensity,
            scores,
            topics_covered,
            summary,
        )

        return (
            f"Saved. Overall {overall} out of 10. "
            f"Weakest area: {weakest}."
        )


# ============================================================
# LIVEKIT SERVER
# ============================================================

server = AgentServer()


# ============================================================
# VOICE SESSION
# ============================================================

@server.rtc_session(agent_name="voice-ai-agent")
async def my_agent(ctx: JobContext):

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    logger.info(
        "Starting interview session in room: %s",
        ctx.room.name,
    )

    # ========================================================
    # AGENT SESSION
    # ========================================================

    session = AgentSession(

        # ----------------------------------------------------
        # SPEECH TO TEXT
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
        # TEXT TO SPEECH
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

        expressive=True,
    )

    # ========================================================
    # START SESSION
    # ========================================================

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

    # ========================================================
    # CONNECT TO ROOM
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
            "Greet the candidate in one or two short sentences as the chairperson of the "
            "mock UPSC interview board, then follow your setup steps."
        )
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    cli.run_app(server)