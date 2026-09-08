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
SOP_DOCS_DIR = "../.docs"  # folder of SOP PDFs, filename ~ process name

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
    for key in index:
        if process_name in key or key in process_name:
            return key
    return None


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a hands-free voice safety assistant on the floor of a
continuous-casting steel plant. You guide workers through Standard Operating
Procedures (SOPs) and you continuously cross-check what the worker is doing
against live machine sensor data (SCADA).

VOICE STYLE
- This is a live, hands-busy voice call. Keep every turn short (1-3 sentences),
  natural, and clear. Speak numbers and units the way a person says them aloud.
- Never dump a whole procedure at once. Give exactly ONE step, then stop and wait.
- If the worker interrupts you, drop what you were saying and respond to them.

SOP HANDLING
- If the worker asks what procedures exist or isn't sure of a name, call
  list_available_sops and read the options back.
- To start, continue, or answer "how do I / what's next", call get_sop_info and
  base your answer ONLY on the returned text. Never invent or recall steps from memory.
- Walk through steps one at a time. After each step, confirm the worker is ready
  before moving on.

LIVE SAFETY MONITORING (this is your most important job)
- If the worker asks about any reading, pressure, temperature, or whether
  something "looks normal", call get_scada_reading first and answer from the live value.
- IMPORTANT: whenever the worker announces or performs a physical action that
  changes the machine's state - for example applying lockout/tagout, isolating an
  accumulator, opening/closing a valve, bleeding a line, or energizing equipment -
  immediately call get_scada_reading to verify the machine actually responded the
  way the current SOP step expects.
- Reason about the reading in context. For example: after lockout, hydraulic
  pressure should fall toward zero; while bleeding a line, pressure must keep
  dropping, never rise. A FAULT bus status or an active alarm is never normal.
- If a live reading is unsafe or contradicts what the step expects (e.g. pressure
  spiking when it should be dropping), INTERRUPT immediately: tell the worker to
  STOP, tell them the specific corrective action (close the valve, step back from
  the block), and do NOT advance to the next step. Recommend escalating to a
  supervisor and say you are logging the anomaly.
- Only resume the procedure once live readings confirm it is safe to continue.
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

        query_terms = [t.lower() for t in query.split() if len(t) > 2]
        lines = full_text.splitlines()
        relevant = []
        for i, line in enumerate(lines):
            if any(term in line.lower() for term in query_terms):
                relevant.extend(lines[max(0, i - 1): i + 3])

        snippet = "\n".join(relevant) if relevant else "\n".join(lines[:40])

        return {
            "process": matched,
            "sop_excerpt": snippet[:2000],
        }

    @function_tool()
    async def list_available_sops(
        self,
        context: RunContext,
    ) -> dict[str, Any]:
        """List all Standard Operating Procedures (SOPs) currently available.

        Use this when the worker asks what procedures exist, isn't sure of the
        exact process name, or when get_sop_info fails to find a match.
        """
        index = _load_sop_index()
        if not index:
            return {"error": "No SOPs are currently loaded."}
        return {"available_sops": sorted(index.keys())}


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