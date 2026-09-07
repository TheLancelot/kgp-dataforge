import os
import glob
import logging
from typing import Any, Optional

import httpx
from pypdf import PdfReader
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
    function_tool,
    RunContext,
)
from livekit.agents.telemetry import set_tracer_provider
from livekit.plugins import silero, noise_cancellation
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

logger = logging.getLogger("factory-agent")
logger.setLevel(logging.INFO)

SCADA_BASE_URL = "http://localhost:8000"
SOP_DOCS_DIR = "./docs"  # folder of SOP PDFs, filename ~ process name

# --- Simple in-memory SOP index (no vector DB, just text + filenames) ---
_sop_cache: dict[str, str] = {}


def _load_sop_index() -> dict[str, str]:
    """Lazily load and cache text of every SOP pdf in SOP_DOCS_DIR."""
    if _sop_cache:
        return _sop_cache
    for path in glob.glob(os.path.join(SOP_DOCS_DIR, "*.pdf")):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            _sop_cache[name.lower()] = text
        except Exception as e:
            logger.warning(f"Failed to read SOP {path}: {e}")
    return _sop_cache


def _find_best_sop_match(process_name: str) -> Optional[str]:
    index = _load_sop_index()
    process_name = process_name.lower().strip()
    if process_name in index:
        return process_name
    # loose substring match either direction
    for key in index:
        if process_name in key or key in process_name:
            return key
    return None


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a factory floor voice assistant guiding workers
through Standard Operating Procedures (SOPs) and helping them interpret live
machine sensor data (SCADA).

Rules:
- Keep responses short (1-3 sentences), spoken naturally — this is a voice call.
- If the worker asks about a procedure, a process, "how do I...", or "what's next",
  call get_sop_info to retrieve the relevant SOP text before answering. Never
  invent steps from memory.
- If the worker asks about a sensor reading, pressure, temperature, or whether
  something looks normal, call get_scada_reading first.
- Walk through SOP steps ONE AT A TIME. After giving a step, ask if the worker
  is ready for the next one, don't dump the whole procedure at once.
- If a SCADA reading looks abnormal or unsafe relative to what the SOP expects,
  say so clearly and recommend stopping / escalating rather than proceeding.
"""
        )

    @function_tool()
    async def get_scada_reading(
        self,
        context: RunContext,
        sensor_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get live SCADA sensor readings from the factory floor.

        Args:
            sensor_name: Optional specific sensor to read (e.g. 'hydraulic_pressure_bar').
                If omitted, returns all current sensor readings.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if sensor_name:
                    resp = await client.get(f"{SCADA_BASE_URL}/sensors/{sensor_name}")
                else:
                    resp = await client.get(f"{SCADA_BASE_URL}/sensors")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"SCADA API call failed: {e}")
            return {"error": f"Could not reach SCADA system: {e}"}

    @function_tool()
    async def get_sop_info(
        self,
        context: RunContext,
        process_name: str,
        query: str,
    ) -> dict[str, Any]:
        """Look up SOP (Standard Operating Procedure) information for a factory process.

        Args:
            process_name: Name of the process/machine (e.g. 'hydraulic valve replacement').
            query: What the worker wants to know, e.g. 'first step', 'next step',
                'safety precautions', 'torque spec for bolt 3'.
        """
        matched = _find_best_sop_match(process_name)
        if not matched:
            available = list(_load_sop_index().keys())
            return {
                "error": f"No SOP found matching '{process_name}'.",
                "available_sops": available,
            }

        full_text = _sop_cache[matched]

        # crude keyword-based relevance: return lines around query terms,
        # falling back to the first chunk (usually intro/step 1) if no match.
        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        lines = full_text.splitlines()
        relevant = []
        for i, line in enumerate(lines):
            if any(term in line.lower() for term in query_terms):
                relevant.extend(lines[max(0, i - 1): i + 3])

        snippet = "\n".join(relevant) if relevant else "\n".join(lines[:40])

        # keep it small — this is going straight into an LLM prompt for voice output
        return {
            "process": matched,
            "sop_excerpt": snippet[:2000],
        }


def prewarm(proc: JobProcess):
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
        llm=inference.LLM(
            model="google/gemini-3-flash-preview",
            extra_kwargs={"max_completion_tokens": 1000},
        ),
        stt=inference.STT(model="google/gemini-3.5-transcribe-live"),
        tts=inference.TTS(model="rime/coda", voice="celeste", language="en"),
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

    await session.say("Hey, I'm your factory floor assistant. What process are you working on?")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )