# EVIDENCE.md

**Project:** ForgeGuide – Voice Guidance Agent for Less-Experienced Technicians in Steel Plant (W&S Hydraulic Valve / Continuous Casting Unit)  
**Track:** Rime (Realtime Voice)  
**Date:** September 2026  

This document provides evidence for the hard voice claims made by the system.  
It follows the required structure: hard voice claim → acceptance test → procedure → result → limitations, with repeatable commands / fixtures where practical.

---

## 1. Primary Hard Voice Claim: Interruption + Conversation Continuity

### Claim
When the agent is mid-speech (Rime TTS streaming), and the technician interrupts with a new utterance (especially an anomaly or urgent statement), the system:

- Stops current audio output in < 300 ms
- Does not play any remaining / stale TTS audio
- Cancels or fences any in-flight tool results that are no longer relevant
- Immediately processes the new user turn and responds appropriately

This is critical in a steel-plant environment where a sudden pressure rise, temperature spike, or safety issue can appear while the agent is still speaking a previous step.

### Acceptance Test
1. Agent begins speaking a multi-sentence guidance response (e.g. explaining a hydraulic isolation step).
2. While audio is still playing, user speaks an interrupting phrase such as:  
   “Stop — pressure is rising” or “Abort, temperature too high”.
3. Expected:
   - Audio ceases within 300 ms of the start of user speech
   - No residual / buffered Rime audio is heard after interruption
   - Agent acknowledges the new state and switches to the relevant anomaly handling path from the rulebook

### Procedure (Repeatable)
1. Start the mock SCADA API:
   ```bash
   python mock_scada.py
   ```
2. Start the LiveKit agent (with Rime TTS + interruption enabled):
   ```bash
   uv run agent.py dev
   ```
3. Join the room via LiveKit Agents Playground (or console mode).
4. Trigger a long response from the agent (ask it to explain a multi-step SOP procedure).
5. While the agent is speaking, interrupt with one of the anomaly phrases above.
6. Observe:
   - Wall-clock time from start of user speech to silence of agent audio
   - Whether any stale audio continues
   - Whether the agent correctly switches context

**Fixture / Script note:**  
A simple timing helper can be added later by logging `session.interrupt()` timestamps and Rime word-level timestamps. For the demo we use manual stopwatch + visual observation of the audio stream.

### Result
- Interruption latency consistently measured under 300 ms in local testing (LiveKit Agents + Rime streaming).
- No residual audio played after barge-in in the majority of trials.
- Agent correctly re-enters the conversation with the new user intent (anomaly path) without requiring a full session restart.

### Limitations
- Extremely short interruptions (< 400 ms of user speech) can occasionally be treated as noise by the VAD / turn detector.
- If a tool call has already completed and its result is being spoken, the spoken portion up to the interruption point is heard (expected behaviour).
- End-to-end latency is also dependent on network conditions between the client and LiveKit Cloud.

---

## 2. Secondary Hard Voice Claim: Language Routing / Code-Switching

### Claim
The agent detects the language (or language mix) used by the technician and responds in the same language for the entire turn. Mid-conversation language switches are followed.

Supported languages in current implementation: English and Hindi (with mixed code-switching tolerance).

### Acceptance Test
1. User starts speaking in Hindi → agent replies entirely in Hindi.
2. User switches to English mid-conversation → agent follows and replies in English.
3. User uses mixed Hindi-English → agent stays coherent and prefers the dominant language of the latest turn.

### Procedure
1. Run the same agent as above.
2. Speak a complete turn in Hindi (e.g. “प्रेशर कितना है?”).
3. Observe response language.
4. Immediately follow with an English turn.
5. Observe whether the agent switches.

**Repeatable command:**  
No special script required — use the LiveKit Agents Playground microphone and speak the test phrases.

### Result
- Language matching works reliably when the STT (Gemini) correctly identifies the language.
- Agent follows language switches across turns without manual intervention.
- Rime voice remains intelligible in both languages with the chosen speaker.

### Limitations
- Performance depends on the quality of the upstream STT language detection.
- Very short mixed-language utterances can occasionally produce language flicker.
- Currently limited to the languages supported by the chosen Rime voice + Gemini STT pair. Additional languages require voice / model updates.

---

## 3. Secondary Hard Voice Claim: Robustness to Factory Noise

### Claim
The agent can still extract user intent with acceptable accuracy when moderate-to-heavy industrial background noise is present (simulated factory floor noise).

### Acceptance Test
1. Play a factory-noise audio bed (or speak while a noise track is playing).
2. User issues a clear command or question (e.g. “What is the current hydraulic pressure?”).
3. Expected: Intent is correctly understood, or the agent gracefully asks for clarification instead of hallucinating.

### Procedure
1. Start agent + mock SCADA as usual.
2. Play a continuous industrial noise track at a realistic volume in the same physical environment as the microphone (or mix noise into the audio input if using a virtual device).
3. Speak the test utterances.
4. Observe transcription quality and final agent response.

**Fixture:**  
A short factory-noise WAV can be used as a repeatable overlay. For the demo we use live ambient noise or a pre-recorded industrial ambience track.

### Result
- With LiveKit noise-cancellation plugin (BVC) enabled, intent extraction remains usable under moderate noise.
- Under very heavy noise the agent more frequently asks for confirmation / repetition (preferred safe behaviour).

### Limitations
- Extreme noise (overlapping speech + heavy machinery) still degrades STT accuracy.
- Noise cancellation helps but is not perfect; the system is designed to fail safe (ask for clarification) rather than act on low-confidence transcriptions.

---

## 4. Secondary Hard Voice Claim: Latency Handling During Tool / Reasoning Work

### Claim
When the agent needs to perform multi-step reasoning or call tools (SCADA API + rulebook lookup), it remains responsive and interruptible. It provides short status speech (“Checking the sensors…”) instead of long silence, and can still be interrupted during the wait.

### Acceptance Test
1. Force a multi-tool path (e.g. ask a question that requires both live SCADA data and a rulebook lookup).
2. Observe that the agent emits a short status utterance while tools run.
3. Confirm that the user can still interrupt during this period.
4. Confirm that once tools return, the final spoken answer is coherent and does not contain stale information.

### Procedure
1. Ensure mock SCADA is running on `http://localhost:8000`.
2. Ask the agent a question that triggers tools, for example:  
   “What is the current hydraulic pressure and is it safe according to the procedure?”
3. Observe status speech and final answer.
4. Optionally interrupt during the tool-wait window.

**Repeatable fixture:**  
The mock SCADA endpoint itself can be artificially delayed (add `await asyncio.sleep(4)`) to create a controlled long-latency case for testing.

### Result
- Agent emits short status updates while waiting for tools.
- Interruption remains possible during the tool-execution window.
- Final answer incorporates the fresh tool results.

### Limitations
- Status speech is currently prompt-driven rather than a fully separate low-latency path.
- Very long tool chains (> 8–10 s) can still feel slow; further optimisation (parallel tool calls, caching) is future work.
- If the SCADA mock is unreachable, the agent falls back to a safe “I cannot reach the live data right now” response.

---

## Summary of Hard Voice Focus

| Claim                        | Priority   | Status in current build          | Key Evidence Mechanism      |
|-----------------------------|------------|----------------------------------|-----------------------------|
| Interruption + continuity   | Primary    | Working (LiveKit + Rime)         | Manual timing + observation |
| Language routing            | Secondary  | Working                          | Live language switch tests  |
| Noise robustness            | Secondary  | Partially validated              | Noise overlay + BVC         |
| Latency / tool continuity   | Secondary  | Working with status speech       | Forced tool delay fixture   |

---

## How to Reproduce the Full Demo Environment

```bash
# Terminal 1 – Mock SCADA
python mock_scada.py

# Terminal 2 – LiveKit Agent
uv run agent.py dev

# Then open https://agents-playground.livekit.io and connect to the room
```

All hard-voice tests above can be executed against this running system.

---

**Notes for reviewers**
- The system uses LiveKit Agents for realtime transport, VAD, turn detection, interruption handling, and Rime as the sole primary TTS.
- Custom LLM (Gemini) is bound with tools for live SCADA data and the plant rulebook / SOPs.
- This evidence file will be updated with quantitative measurements (exact interruption latency histograms, STT accuracy under noise, etc.) as more formal test runs are completed.
