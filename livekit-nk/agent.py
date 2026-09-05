import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    ChatContext,
    ChatMessage,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RunContext,
    StopResponse,
    WorkerOptions,
    cli,
    function_tool,
    inference,
)
from livekit.plugins import noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv("../.env")
logger = logging.getLogger("wns-valve-agent")
logging.basicConfig(level=logging.INFO)


# ──────────────────────────────────────────────────────────────────────────────
# 1. DETERMINISTIC RULEBOOK  (SOP + anomaly overrides)
# ──────────────────────────────────────────────────────────────────────────────

SOP_TITLE = "W and S Unit Hydraulic Valve Replacement, Continuous Casting"

SOP_STEPS: list[str] = [
    "Step 1. Verify the continuous caster strand is fully stopped and the dummy bar is mechanically secured.",
    "Step 2. Execute Lockout Tagout on the main Hydraulic Power Unit powering the W and S zone.",
    "Step 3. Isolate the local nitrogen bladder accumulator for the specific pinch roll segment.",
    "Step 4. Manually bleed residual line pressure via the manifold dump valve until the local analog gauge reads zero bar.",
    "Step 5. Disconnect the electrical M12 connectors from the valve's solenoids and the LVDT position sensor.",
    "Step 6. Unbolt the proportional directional valve from the manifold block using a cross pattern sequence to prevent thread binding.",
    "Step 7. Inspect the manifold mating surface for scoring, and verify all old O rings are removed.",
    "Step 8. Mount the replacement valve with new O rings, torquing the bolts to the specified limit in a cross pattern.",
    "Step 9. Reconnect the solenoid and LVDT electrical connectors.",
    "Step 10. Remove Lockout Tagout, slowly open the isolation block to pressurize the segment, and actuate the manual override to bleed trapped air.",
    "Step 11. Confirm roll gap calibration and valve stroke response via the SCADA interface.",
]


@dataclass
class AnomalyRule:
    id: str
    action: str          # "HALT" | "DIVERT"
    hazard: str
    directive: str       # spoken verbatim by Rime
    # each inner list = ALL tokens must be present in the utterance
    triggers: list[list[str]] = field(default_factory=list)


ANOMALY_RULES: list[AnomalyRule] = [
    AnomalyRule(
        id="ACCUMULATOR_ISOLATION_FAILURE",
        action="HALT",
        hazard="Accumulator isolation failure. Severe hydraulic injection hazard.",
        directive=(
            "Halt. Do not loosen the manifold bolts. "
            "Close the main zone isolation valve immediately, and verify the accumulator dump block. "
            "Hydraulic injection hazard. Confirm when the gauge reads zero bar."
        ),
        triggers=[
            ["pressure", "stuck"], ["gauge", "stuck"], ["gauge", "frozen"],
            ["pressure", "not", "drop"], ["pressure", "won't", "drop"],
            ["pressure", "wont", "drop"], ["still", "40"], ["40", "bar"],
            ["pressure", "rose"], ["pressure", "rising"], ["pressure", "spiked"],
            ["residual", "pressure"], ["holding", "pressure"],
        ],
    ),
    AnomalyRule(
        id="FLUID_WEEP",
        action="HALT",
        hazard="Pinched O ring or scored manifold surface preventing a flush seal.",
        directive=(
            "Halt. Stop pressurization. Depressurize the line immediately. "
            "Remove the valve and check the O ring seating and the manifold mating surface for scoring."
        ),
        triggers=[
            ["weep"], ["weeping"], ["leak"], ["leaking"], ["seep"], ["seeping"],
            ["fluid", "coming"], ["oil", "dripping"], ["dripping"], ["wet", "block"],
        ],
    ),
    AnomalyRule(
        id="PROFIBUS_FAULT",
        action="DIVERT",
        hazard="Faulty pin connection or incorrect node addressing on the replacement valve.",
        directive=(
            "Divert. Do not start the Hydraulic Power Unit pump. "
            "Disconnect the M12 connector, inspect the pins for damage, "
            "and verify the replacement valve's hardware node address."
        ),
        triggers=[
            ["profibus"], ["communication", "fault"], ["comm", "fault"],
            ["comms", "fault"], ["bus", "fault"], ["bus", "error"],
            ["scada", "fault"], ["scada", "error"], ["node", "fault"],
            ["no", "signal", "scada"], ["lvdt", "fault"],
        ],
    ),
    AnomalyRule(
        id="ROLL_CREEP",
        action="HALT",
        hazard="Valve spool is bypassing fluid in the neutral position.",
        directive=(
            "Halt. Crush hazard. The cylinder is drifting. "
            "Clear the roll gap, lock out the Hydraulic Power Unit immediately. "
            "The replacement valve requires mechanical zeroing before it goes back in service."
        ),
        triggers=[
            ["creep"], ["creeping"], ["drift"], ["drifting"], ["sinking"],
            ["roll", "moving"], ["roll", "coming", "down"], ["cylinder", "dropping"],
            ["going", "down", "own"],
        ],
    ),
    AnomalyRule(
        id="MANIFOLD_OVERHEAT",
        action="HALT",
        hazard="Local cooling failure or fluid throttling across a relief valve.",
        directive=(
            "Halt. Burn hazard. Step back from the manifold. "
            "Verify the local heat exchanger water flow before proceeding with maintenance."
        ),
        triggers=[
            ["too", "hot"], ["hot", "touch"], ["burning", "hot"], ["scalding"],
            ["overheat"], ["overheating"], ["smoking"], ["steam"], ["block", "hot"],
        ],
    ),
]

# Generic hard stop if the tech panics but says nothing diagnostic yet.
GENERIC_STOP_TOKENS = {"stop", "abort", "emergency", "danger", "help", "halt"}
GENERIC_STOP_DIRECTIVE = (
    "Holding the procedure. Step back to a safe position. "
    "Tell me what you are seeing and I will route the correct action."
)

_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def match_anomaly(utterance: str) -> Optional[AnomalyRule]:
    """Deterministic rulebook lookup. Runs BEFORE any LLM inference."""
    toks = set(_tokens(utterance))
    if not toks:
        return None
    best: Optional[AnomalyRule] = None
    best_specificity = 0
    for rule in ANOMALY_RULES:
        for group in rule.triggers:
            if all(t in toks for t in group):
                if len(group) > best_specificity:
                    best, best_specificity = rule, len(group)
    return best


def is_generic_stop(utterance: str) -> bool:
    toks = set(_tokens(utterance))
    return bool(toks & GENERIC_STOP_TOKENS) and len(toks) <= 6


# ──────────────────────────────────────────────────────────────────────────────
# 2. SESSION STATE  (procedure pointer + fence)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProcedureState:
    step_index: int = 0                 # 0-based pointer into SOP_STEPS
    started: bool = False
    halted: bool = False
    active_anomaly: Optional[str] = None
    fenced_step_index: Optional[int] = None   # step invalidated by the anomaly

    def current_step_text(self) -> str:
        return SOP_STEPS[self.step_index]


# ──────────────────────────────────────────────────────────────────────────────
# 3. AGENT
# ──────────────────────────────────────────────────────────────────────────────

INSTRUCTIONS = f"""
You are FORGE, a hands-free industrial process control aid guiding a technician through:
"{SOP_TITLE}".

The technician is in a hot, cramped, high-noise plant. He cannot see any screen and cannot
use his hands. Audio is your only channel.

HARD RULES
1. NEVER invent, summarise, reorder or paraphrase a procedure step. Steps only come from the
   tools: start_procedure, next_step, repeat_step, previous_step, go_to_step, where_am_i.
   Read the tool's returned text VERBATIM.
2. Maximum 1 to 2 short sentences per turn unless you are reading a step.
3. Read exactly ONE step at a time, then stop and wait. Never chain steps.
4. If the procedure is HALTED, refuse to advance. Say the hazard is unresolved and tell him to
   say "anomaly cleared" once the corrective action is done.
5. Any safety directive already spoken by the system overrides everything earlier in the
   conversation. Instructions marked [FENCED] are obsolete. Never re-read them from memory.
6. If you are unsure or the request is outside this SOP, say so plainly. Do not guess.
7. No filler, no pleasantries, no emojis, no markdown. Plain spoken English. Digits as words.
8. Confirm-back is mandatory after any hazard: ask him to verbally confirm the corrective action.
"""


class ProcessControlAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    # ── Deterministic safety interceptor ────────────────────────────────────
    # Fires the instant the user's turn is committed, BEFORE the LLM is called.
    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        utterance = (new_message.text_content or "").strip()
        if not utterance:
            return

        state: ProcedureState = self.session.userdata
        rule = match_anomaly(utterance)

        if rule is None:
            if is_generic_stop(utterance) and not state.halted:
                await self._emergency_override(
                    turn_ctx,
                    state,
                    anomaly_id="UNSPECIFIED_HAZARD",
                    hazard="Unspecified hazard reported by operator.",
                    directive=GENERIC_STOP_DIRECTIVE,
                    action="HALT",
                )
                raise StopResponse()
            return

        await self._emergency_override(
            turn_ctx,
            state,
            anomaly_id=rule.id,
            hazard=rule.hazard,
            directive=rule.directive,
            action=rule.action,
        )
        raise StopResponse()  # skip LLM generation entirely for this turn

    async def _emergency_override(
        self,
        turn_ctx: ChatContext,
        state: ProcedureState,
        *,
        anomaly_id: str,
        hazard: str,
        directive: str,
        action: str,
    ) -> None:
        # 1. Flush: kill in-flight LLM stream + queued Rime TTS frames.
        await self.session.interrupt()

        # 2. Context fencing: the step we were on is now invalid.
        state.halted = True
        state.active_anomaly = anomaly_id
        state.fenced_step_index = state.step_index if state.started else None

        fenced_txt = (
            f'[FENCED - OBSOLETE] "{state.current_step_text()}"'
            if state.started
            else "[FENCED] No step in progress."
        )
        turn_ctx.add_message(
            role="system",
            content=(
                f"### EMERGENCY OVERRIDE ({action}) :: {anomaly_id}\n"
                f"HAZARD: {hazard}\n"
                f"{fenced_txt}\n"
                f"The following directive was just spoken to the operator by the safety layer:\n"
                f'"{directive}"\n'
                "The procedure is HALTED. Do not advance. Do not repeat the fenced step. "
                "Answer only follow-up questions about this hazard until the operator says "
                "the anomaly is cleared."
            ),
        )

        logger.warning("ANOMALY %s (%s) -> fencing step %s", anomaly_id, action, state.step_index + 1)

        # 3. Priority routing: speak the directive immediately, ahead of everything.
        await self.session.say(directive, allow_interruptions=True)

    # ── SOP tools ───────────────────────────────────────────────────────────

    @function_tool
    async def start_procedure(self, ctx: RunContext[ProcedureState]) -> str:
        """Begin the valve replacement procedure from step one."""
        s = ctx.userdata
        if s.halted:
            return self._blocked(s)
        s.started, s.step_index = True, 0
        return f"Read verbatim: Starting the procedure. {s.current_step_text()}"

    @function_tool
    async def next_step(self, ctx: RunContext[ProcedureState]) -> str:
        """Advance to and read the next step of the SOP. Use when the technician
        confirms the current step is complete."""
        s = ctx.userdata
        if s.halted:
            return self._blocked(s)
        if not s.started:
            s.started = True
            return f"Read verbatim: {s.current_step_text()}"
        if s.step_index >= len(SOP_STEPS) - 1:
            return ("Read verbatim: That was the final step. The valve replacement procedure "
                    "is complete. Log the work order and clear the zone.")
        s.step_index += 1
        return f"Read verbatim: {s.current_step_text()}"

    @function_tool
    async def repeat_step(self, ctx: RunContext[ProcedureState]) -> str:
        """Repeat the current step verbatim."""
        s = ctx.userdata
        if not s.started:
            return "Read verbatim: The procedure has not started yet. Say begin to start."
        return f"Read verbatim: {s.current_step_text()}"

    @function_tool
    async def previous_step(self, ctx: RunContext[ProcedureState]) -> str:
        """Go back one step and read it."""
        s = ctx.userdata
        if s.halted:
            return self._blocked(s)
        s.step_index = max(0, s.step_index - 1)
        return f"Read verbatim: Going back. {s.current_step_text()}"

    @function_tool
    async def go_to_step(self, ctx: RunContext[ProcedureState], step_number: int) -> str:
        """Jump to a specific step number (1 to 11) and read it.

        Args:
            step_number: The 1-based SOP step number requested by the technician.
        """
        s = ctx.userdata
        if s.halted:
            return self._blocked(s)
        if not 1 <= step_number <= len(SOP_STEPS):
            return f"Read verbatim: This procedure only has {len(SOP_STEPS)} steps."
        s.started, s.step_index = True, step_number - 1
        return f"Read verbatim: {s.current_step_text()}"

    @function_tool
    async def where_am_i(self, ctx: RunContext[ProcedureState]) -> str:
        """State the current position in the procedure and any active hazard."""
        s = ctx.userdata
        if not s.started:
            return "Read verbatim: The procedure has not started yet."
        pos = f"You are on step {s.step_index + 1} of {len(SOP_STEPS)}."
        if s.halted:
            return (f"Read verbatim: {pos} The procedure is halted due to "
                    f"{s.active_anomaly.replace('_', ' ').lower()}.")
        return f"Read verbatim: {pos} {s.current_step_text()}"

    @function_tool
    async def clear_anomaly(self, ctx: RunContext[ProcedureState]) -> str:
        """Clear the active hazard and resume the procedure. ONLY call this when the
        technician explicitly confirms the corrective action is complete, for example
        'anomaly cleared', 'pressure is at zero now', 'leak is fixed', 'resume'."""
        s = ctx.userdata
        if not s.halted:
            return "Read verbatim: There is no active hazard. The procedure is running normally."
        cleared = s.active_anomaly
        s.halted, s.active_anomaly, s.fenced_step_index = False, None, None
        logger.info("ANOMALY CLEARED: %s -> resuming at step %s", cleared, s.step_index + 1)
        return (f"Read verbatim: Hazard cleared. Resuming the procedure. "
                f"Re-confirming your current step. {s.current_step_text()}")

    @staticmethod
    def _blocked(s: ProcedureState) -> str:
        return (
            "BLOCKED. The procedure is halted by an active hazard "
            f"({s.active_anomaly}). Tell the operator you cannot advance until the corrective "
            "action is confirmed, and ask him to say 'anomaly cleared' when it is done."
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. WORKER
# ──────────────────────────────────────────────────────────────────────────────

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load(
        min_silence_duration=0.20,   # snappier end-of-turn in a noisy plant
        activation_threshold=0.55,   # slightly hot mic tolerance
    )


async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.wait_for_participant()

    session = AgentSession[ProcedureState](
        userdata=ProcedureState(),

        llm=inference.LLM(
            model="google/gemini-3-flash-preview",
            extra_kwargs={"max_completion_tokens": 400},
        ),
        stt=inference.STT(model="google/gemini-3.5-transcribe-live"),
        tts=inference.TTS(model="rime/coda", voice="celeste", language="en"),

        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),

        # ── full-duplex / barge-in tuning ───────────────────────────────
        allow_interruptions=True,
        min_interruption_duration=0.20,   # ~200ms of speech kills playback
        min_interruption_words=0,         # a single shouted "wait" counts
        min_endpointing_delay=0.35,
        max_endpointing_delay=3.0,
        preemptive_generation=True,       # cuts first-token latency
    )

    await session.start(
        room=ctx.room,
        agent=ProcessControlAgent(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await session.say(
        "Voice process control assistant online. Hydraulic valve replacement, W and S unit. "
        "Say begin to start, or report anything you see and I will halt the procedure."
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))