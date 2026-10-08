import logging

from dotenv import load_dotenv

from livekit.plugins import sarvam
from livekit.plugins import ai_coustics

from prompts import build_instructions

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    cli,
    inference,
    room_io,
)


logger = logging.getLogger("agent")

load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            # LLM = the brain of the agent
            llm=inference.LLM(
                model="google/gemma-4-31b-it"
            ),

            # Our Day 2 mentor personality
            instructions=build_instructions(),
        )


server = AgentServer()


@server.rtc_session(agent_name="voice-ai-agent")
async def my_agent(ctx: JobContext):

    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(

        # ==========================================
        # SPEECH TO TEXT
        # Sarvam understands Indian languages
        # and code-mixed Hinglish.
        # ==========================================

        stt=sarvam.STT(
            language="hi-IN",
            model="saaras:v4",
            mode="codemix",
            sample_rate=16000,
            high_vad_sensitivity=True,
        ),

        # ==========================================
        # STT CONTEXT
        # ==========================================

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
                "enabled": True
            },
        ),

        # ==========================================
        # TEXT TO SPEECH
        # ==========================================

        tts=sarvam.TTS(
            target_language_code="hi-IN",
            model="bulbul:v3",
            speaker="shubh",
            speech_sample_rate=22050,
            pace=1.0,
        ),

        # ==========================================
        # TURN DETECTION
        # ==========================================

        turn_handling=TurnHandlingOptions(

            # Detect when the student has finished speaking
            turn_detection=inference.TurnDetector(),

            # Distinguish real interruptions from
            # small backchannel sounds like "hmm"
            interruption={
                "mode": "adaptive"
            },

            # Start generating before the complete
            # turn is finished when possible
            preemptive_generation={
                "enabled": True
            },
        ),

        # Sarvam TTS supports expressive speech
        expressive=True,
    )

    # ==========================================
    # START SESSION
    # ==========================================

    await session.start(
        agent=Assistant(),
        room=ctx.room,

        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(

                # Noise cancellation / enhancement
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    # Connect the agent to the LiveKit room
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)