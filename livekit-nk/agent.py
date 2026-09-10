import os

from dotenv import load_dotenv
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.util.types import AttributeValue
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    inference,
)
from livekit.agents.telemetry import set_tracer_provider
from livekit.plugins import google, rime, silero, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv("../.env")  


def setup_langfuse(
    metadata: dict[str, AttributeValue] | None = None,
) -> TracerProvider:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

    if not public_key or not secret_key or not base_url:
        raise ValueError(
            "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and "
            "LANGFUSE_BASE_URL (or LANGFUSE_HOST) must be set"
        )

    trace_provider = TracerProvider()
    set_tracer_provider(trace_provider, metadata=metadata)
    Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        tracer_provider=trace_provider,
        should_export_span=lambda span: True,
    )
    return trace_provider

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

    trace_provider = setup_langfuse(
        metadata={"langfuse.session.id": ctx.room.name}
    )

    async def flush_trace() -> None:
        trace_provider.force_flush()

    ctx.add_shutdown_callback(flush_trace)

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
    await session.say("Hey! How are you Tushar? Are you enjoying poker")

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )