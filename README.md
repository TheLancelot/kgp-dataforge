### Core  
Voice-native guidance agent for continuous maintenance workflows and processes in industrial environments

### Target User
Less-experienced technicians working on the Withdrawal & Straightening (W&S) unit of a continuous casting line in a steel plant. These technicians operate in hot, noisy, high-risk environments where their hands are often occupied, screens are impractical, and procedural mistakes can cause serious safety incidents or costly downtime.

### Problem
Complex maintenance tasks such as hydraulic valve replacement require strict adherence to multi-step Standard Operating Procedures and rapid reaction to real-time process anomalies (stuck pressure gauges, overheating manifolds, drifting pinch rolls, communication faults, etc.).  

Less-trained technicians frequently lack complete procedural knowledge and cannot safely consult paper checklists or tablet interfaces while working. Radio calls to supervisors introduce delay. Existing digital tools fail because they are not hands-free, not interruptible, and not tightly coupled to live plant data.

### Why Voice Is Essential
In this environment, speech is the only practical primary interface. Removing spoken guidance would make the product materially worse: the technician’s hands and eyes are already committed to the physical task. A chatbot with a play button or a screen-based checklist is unusable under real plant conditions.

### Solution Overview
Core is a realtime voice agent that acts as an interruptible co-pilot for the technician. It:

- Guides the user step-by-step through maintenance SOPs
- Continuously listens for anomaly statements and triggers the corresponding emergency override from a deterministic rulebook
- Retrieves live sensor readings (pressure, temperature, accumulator, roll position, valve stroke, Profibus status) from a mock SCADA system via tools
- Responds in the same language the technician is speaking (including mid-conversation code-switching)
- Stays fully interruptible — any barge-in immediately stops Rime audio and reorients the conversation
- Remains responsive while performing tool calls or multi-step reasoning

The system is built on LiveKit Agents for realtime transport and turn handling, Gemini for speech recognition and reasoning, and Rime (`coda` voice) as the primary spoken output.

### Hard Voice Problems Addressed
- **Interruption + conversation continuity** during tool work and mid-speech barge-ins
- **Language routing / code-switching**
- **Robustness under factory noise**
- **Graceful latency handling** while querying live data and documents

## Python Setup

The commands below are for Windows PowerShell and should be run from the repository root (`kgp_dataforge`). Python 3.10 or newer is recommended.

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell blocks activation for the current session, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Then activate the environment again.

### 2. Install Python dependencies

```powershell
python -m pip install -r requirements.txt
```

The pinned versions in `requirements.txt` match the development environment used for this project.

### 3. Install the LiveKit CLI

Install the LiveKit command-line tool with WinGet:

```powershell
winget install LiveKit.LiveKitCLI
```

The LiveKit Agents plugins require local model files for VAD and turn detection. Download them once after installing the Python dependencies:

```powershell
python -m livekit.agents download-files
```

### 4. Create the required service accounts and API keys

Create accounts and obtain credentials from each service. Keep all credentials private and never commit them to Git.

1. **Rime**: create an account at [Rime](https://app.rime.ai/tokens/) and create an API token. This is used for the Rime `coda` voice.
2. **Google Gemini**: create an API key in [Google AI Studio](https://aistudio.google.com/apikey). Gemini is used for speech recognition and LLM reasoning.
3. **LiveKit Cloud**: create a project in [LiveKit Cloud](https://cloud.livekit.io/), then copy its WebSocket URL, API key, and API secret. These credentials connect the agent to the realtime room.
4. **Langfuse**: create a project in [Langfuse Cloud](https://cloud.langfuse.com/), then create a public key and secret key. The current agent uses Langfuse for tracing and requires the project base URL.

Create a `.env` file in the repository root (`kgp_dataforge/.env`):

```dotenv
RIME_API_KEY=your_rime_api_key
GEMINI_API_KEY=your_gemini_api_key
GOOGLE_API_KEY=your_gemini_api_key

LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

### 5. Start the agent

Start the SCADA API in a separate terminal from the repository root:

```powershell
cd src
python -m uvicorn api.scada:app --host 0.0.0.0 --port 8000 --reload
```

In another terminal, activate the same virtual environment, move into `app`, and start Core in console mode:

```powershell
cd app
python final_agent.py console
```

The agent will connect to LiveKit, wait for a participant, and greet the technician. 

### 6. Try the Demo Script

To truly see how Core works—especially its ability to handle sudden interruptions and fetch live sensor data—we highly recommend using our demo script! You can read the user prompts below aloud to the agent to test the workflow firsthand and see how it reacts.

**Demo Flow:**
* **You:** "Hey, I need to do some maintenance on the caster today. Can you list the available standard operating procedures?"
* **Agent:** *(Lists procedures like W and S Unit Hydraulic Valve Replacement)*
* **You:** "Let's execute the W and S Unit Hydraulic Valve Replacement. Start walking me through the procedure."
* **You:** *(While the agent is reading Step 2, interrupt it loudly)* "Wait, stop right there. Before I apply the lockout tagout, what is the live pressure reading on the SCADA dashboard?"

Once you interrupt, the agent will instantly halt its speech, fetch the live SCADA data, and await your confirmation before proceeding. 

**Bonus Test:** Feel free to go off-script and throw in your own sudden safety hazards (for example, shouting *"Stop, there is a fire!"*) to test how the agent handles emergency protocols and abandons the standard SOP.
