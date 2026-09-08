# ForgeGuide

Voice-native guidance agent for continuous-caster maintenance workflows. ForgeGuide combines LiveKit realtime voice transport, Gemini speech and reasoning, Rime text-to-speech, live SCADA readings, and SOP document lookup.

## Python Setup

The commands below are for Windows PowerShell and should be run from the repository root (`kgp_dataforge`). Python 3.10 or newer is recommended.

### 1. Create and activate a virtual environment

```powershell
py -m venv .venv
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

`final_agent.py` loads this file with `load_dotenv("../.env")`, so the agent must be started from the `livekit-nk` directory. The `.env` file is ignored by Git; do not paste real keys into the README, source files, screenshots, or issue reports.

### 5. Start the agent

Start the SCADA API in a separate terminal from the repository root:

```powershell
python -m uvicorn api.scada:app --host 0.0.0.0 --port 8000 --reload
```

In another terminal, activate the same virtual environment, move into `livekit-nk`, and start ForgeGuide in console mode:

```powershell
cd livekit-nk
python final_agent.py console
```

The agent will connect to LiveKit, wait for a participant, and greet the technician. The `docs` directory must remain beside `final_agent.py` so the SOPs can be loaded.
