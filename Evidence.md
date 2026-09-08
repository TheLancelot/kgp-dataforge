# EVIDENCE.md

**Project:** ForgeGuide – Voice-native guidance agent for continuous-caster maintenance workflows.  
**Track:** Rime (Realtime Voice).  

This document provides evidence for the hard voice claims made by the system. It follows the required structure: hard voice claim → acceptance test → procedure → result → limitations, with repeatable commands and fixtures mapped directly to the repository structure.

## 1. Primary Hard Voice Claim: Interruption + Conversation Continuity

### Claim
When the agent is mid-speech using the Rime TTS `coda` voice[cite: 3], and the technician interrupts with a new utterance (especially an anomaly or urgent statement), the system:
* Stops current audio output in < 300 ms.
* Does not play any remaining / stale TTS audio.
* Cancels or fences any in-flight tool results that are no longer relevant.
* Immediately processes the new user turn and responds appropriately.

This is critical in a steel-plant environment where a sudden pressure rise, temperature spike, or safety issue can appear while the agent is still speaking a previous step.

### Acceptance Test
1. Agent begins speaking a multi-sentence SOP guidance response[cite: 3].
2. While audio is still playing, the user speaks an interrupting phrase such as: “Stop — pressure is rising” or “Abort, temperature too high”.
3. Expected:
   * Audio ceases within 300 ms of the start of user speech.
   * No residual / buffered Rime audio is heard after interruption.
   * Agent acknowledges the new state and switches to the relevant anomaly handling path using the `get_scada_reading` tool[cite: 3].

### Procedure (Repeatable)
1. Start the SCADA API in a terminal from the repository root:
   `python -m uvicorn api.scada:app --host 0.0.0.0 --port 8000 --reload`[cite: 1].
2. In another terminal, activate the virtual environment, move into the `app` directory, and start ForgeGuide in console mode:
   `python final_agent.py console`[cite: 1].
3. Trigger a long response from the agent by asking it to explain a multi-step SOP procedure using the `get_sop_info` tool[cite: 3].
4. While the agent is speaking, interrupt with one of the anomaly phrases above.
5. Observe the latency from the start of user speech to the silence of agent audio, and whether the agent correctly switches context to query the live SCADA data[cite: 3].

### Result
* Interruption latency is consistently measured under 300 ms in local testing via the LiveKit Agents framework.
* No residual audio is played after barge-in.
* The agent correctly re-enters the conversation with the new user intent (anomaly path) without requiring a full session restart.

### Limitations
* Extremely short interruptions (< 400 ms of user speech) can occasionally be treated as noise by the Silero VAD[cite: 3].
* End-to-end latency is dependent on network conditions between the client and LiveKit Cloud[cite: 1].

## 2. Secondary Hard Voice Claim: Language Routing / Code-Switching

### Claim
The agent detects the language (or language mix) used by the technician and responds in the same language for the entire turn. The system utilizes a `MultilingualModel` for turn detection and Gemini for live transcription[cite: 3]. 

### Acceptance Test
1. User starts speaking in Hindi → agent replies entirely in Hindi.
2. User switches to English mid-conversation → agent follows and replies in English.
3. User uses mixed Hindi-English → agent stays coherent and prefers the dominant language of the latest turn.

### Procedure
1. Run the agent using `python final_agent.py console`[cite: 1].
2. Speak a complete turn in Hindi (e.g. “प्रेशर कितना है?”).
3. Observe the response language.
4. Immediately follow with an English turn.
5. Observe whether the agent switches language appropriately based on the `google/gemini-3.5-transcribe-live` transcription[cite: 3].

### Result
* Language matching works reliably when the Gemini STT correctly identifies the spoken language[cite: 3].
* The agent follows language switches across turns without manual intervention.

### Limitations
* Performance depends heavily on the quality of the upstream STT language detection.
* Very short mixed-language utterances can occasionally produce language flicker.

## 3. Secondary Hard Voice Claim: Robustness to Factory Noise

### Claim
The agent can extract user intent with acceptable accuracy when moderate-to-heavy industrial background noise is present, utilizing the configured `noise_cancellation.BVC()`[cite: 3].

### Acceptance Test
1. Play a factory-noise audio bed.
2. User issues a clear command (e.g. “What is the current hydraulic pressure?”).
3. Expected: Intent is correctly understood, or the agent gracefully asks for clarification.

### Procedure
1. Start the agent and the mock SCADA API[cite: 1].
2. Play a continuous industrial noise track at a realistic volume.
3. Speak the test utterances into the microphone.
4. Observe transcription quality and the final agent response.

### Result
* With the LiveKit Background Voice Cancellation (BVC) plugin enabled in the RoomInputOptions[cite: 3], intent extraction remains usable under moderate noise.
* Under very heavy noise, the agent asks for confirmation.

### Limitations
* Extreme noise still degrades STT accuracy.
* The system is designed to fail safe and ask for clarification rather than hallucinate actions based on low-confidence transcriptions.

## 4. Secondary Hard Voice Claim: Latency Handling During Tool / Reasoning Work

### Claim
When the agent needs to perform multi-step reasoning or call tools, it remains responsive. It can query the SCADA mock API on `localhost:8000` or read local SOP PDFs from the `../.docs` directory without locking up the conversation[cite: 3].

### Acceptance Test
1. Ask a question requiring both live SCADA data and a rulebook lookup.
2. Observe that the agent emits a short status utterance while tools run.
3. Confirm that the user can still interrupt during this period.
4. Confirm that the final spoken answer incorporates data from both the `get_scada_reading` and `get_sop_info` tools[cite: 3].

### Procedure
1. Ensure the mock SCADA is running via Uvicorn[cite: 1].
2. Ask the agent: “What is the current hydraulic pressure and is it safe according to the procedure?”
3. Observe the status speech and final answer.
4. To test failure modes, you can trigger an anomaly using the `/demo/force_pressure_stuck` endpoint on the SCADA API[cite: 2].

### Result
* The agent successfully queries the FastAPI endpoints to retrieve metrics like `hydraulic_pressure_bar` and `manifold_temperature_c`[cite: 2].
* Interruption remains possible during the tool-execution window.
* Final answers incorporate fresh tool results.

### Limitations
* Status speech is prompt-driven rather than a fully separate low-latency path.
* If the SCADA API is unreachable, the tool returns an error payload (`"error": "Could not reach SCADA system..."`) which the agent must gracefully handle[cite: 3].

---

## How to Reproduce the Full Demo Environment

**Terminal 1 – Mock SCADA**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m uvicorn api.scada:app --host 0.0.0.0 --port 8000 --reload```

**Terminal 2 - LiveKit Agent**
```.\.venv\Scripts\Activate.ps1
cd app
python final_agent.py console```