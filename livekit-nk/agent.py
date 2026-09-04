from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    inference
)
from livekit.plugins import google, rime, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv("../.env")  

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful, concise voice assistant.
Keep every response short (1-3 sentences). Speak naturally.
"""
        )

def prewarm(proc: JobProcess):
    # Load VAD once when the worker starts (faster later)
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.wait_for_participant()

    session = AgentSession(

        # llm=google.LLM(model="gemini-3.5-flash-lite"),  
        llm=inference.LLM(
        model="google/gemini-3-flash-preview",
        extra_kwargs={
            "max_completion_tokens": 1000
        }),

        stt=inference.STT(
        model="google/gemini-3.5-transcribe-live",
       ),

        tts=inference.TTS(
        model="rime/coda",
        voice="celeste",
        language="en"
        ),

        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # First message when the user joins
    await session.say("Hey I am your agent, at your service")

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )