from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import math
import time
import random
import threading
from typing import Optional
from pydantic import BaseModel

app = FastAPI(title="Mock SCADA - W&S Hydraulic Valve")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SensorReading(BaseModel):
    timestamp: float
    hydraulic_pressure_bar: float
    manifold_temperature_c: float
    accumulator_pressure_bar: float
    pinch_roll_position_mm: float
    valve_stroke_percent: float
    profibus_status: str
    system_mode: str
    alarm: bool
    notes: str = ""


# ---------------------------------------------------------------------------
# Server-side demo state.  The UI mutates this via /demo/* endpoints, and the
# voice agent (and the dashboard) both read whatever the plant is currently
# doing.  Nothing about the anomaly is ever revealed to the agent directly –
# it can only observe the numbers, exactly like a real operator.
# ---------------------------------------------------------------------------
start_time = time.time()
_lock = threading.Lock()

DRAIN_SECONDS = 8.0

DEMO = {
    "mode": "energized",          # energized | draining | locked_out | anomaly
    "mode_since": time.time(),
    "return_mode": "locked_out",  # where to go after an anomaly self-clears
    "anomaly_peak": 215.0,
    "anomaly_duration": 900.0,
}


def _advance_state():
    """Handle automatic timed transitions (draining -> locked_out, anomaly -> clear)."""
    now = time.time()
    with _lock:
        mode = DEMO["mode"]
        elapsed = now - DEMO["mode_since"]

        if mode == "draining" and elapsed > DRAIN_SECONDS:
            DEMO["mode"] = "locked_out"
            DEMO["mode_since"] = now
        elif mode == "anomaly" and elapsed > DEMO["anomaly_duration"]:
            # Anomaly "resolves" itself (operator + agent handled it)
            DEMO["mode"] = DEMO["return_mode"]
            DEMO["mode_since"] = now

        return DEMO["mode"], now - DEMO["mode_since"]


def generate_reading() -> SensorReading:
    mode, elapsed = _advance_state()
    t = time.time() - start_time

    # Baseline signals that always drift naturally
    temp = 55 + 12 * math.sin(t * 0.08 + 1) + random.uniform(-1.5, 1.5)
    accumulator = 130 + 15 * math.sin(t * 0.12) + random.uniform(-2, 2)
    roll_pos = 22 + 4 * math.sin(t * 0.25) + random.uniform(-0.8, 0.8)
    stroke = 48 + 18 * math.sin(t * 0.18) + random.uniform(-2, 2)

    profibus = "OK"
    alarm = False

    if mode == "energized":
        hydraulic = 178 + 3 * math.sin(t * 0.2) + random.uniform(-1.5, 1.5)
        system_mode = "ENERGIZED"
        notes = "Normal operation - HPU energized and pressurized."

    elif mode == "draining":
        frac = min(1.0, elapsed / DRAIN_SECONDS)
        hydraulic = max(0.0, 178 * (1 - frac)) + random.uniform(-1, 1)
        hydraulic = max(0.0, hydraulic)
        system_mode = "LOCKOUT_IN_PROGRESS"
        notes = "Lockout/Tagout applied - hydraulic pressure bleeding down."

    elif mode == "locked_out":
        hydraulic = max(0.0, 0.6 + random.uniform(-0.4, 0.6))
        system_mode = "LOCKED_OUT"
        notes = "System locked out - zero-energy state confirmed."

    elif mode == "anomaly":
        peak = DEMO["anomaly_peak"]
        ramp = min(1.0, elapsed / 2.0)  # spikes up fast (~2s)
        hydraulic = peak * ramp + 4 * math.sin(t * 1.5) + random.uniform(-2, 2)
        hydraulic = max(0.0, hydraulic)
        accumulator = min(180, accumulator + 25)
        profibus = "FAULT"
        alarm = True
        system_mode = "ALARM"
        notes = "ALARM: manifold line pressure above safe limit - unexpected rise."

    else:
        hydraulic = 100.0
        system_mode = "UNKNOWN"
        notes = ""

    # Clamp remaining channels
    temp = max(25, min(110, temp))
    accumulator = max(50, min(180, accumulator))
    roll_pos = max(0, min(50, roll_pos))
    stroke = max(0, min(100, stroke))
    hydraulic = max(0, min(260, hydraulic))

    return SensorReading(
        timestamp=time.time(),
        hydraulic_pressure_bar=round(hydraulic, 1),
        manifold_temperature_c=round(temp, 1),
        accumulator_pressure_bar=round(accumulator, 1),
        pinch_roll_position_mm=round(roll_pos, 2),
        valve_stroke_percent=round(stroke, 1),
        profibus_status=profibus,
        system_mode=system_mode,
        alarm=alarm,
        notes=notes,
    )


@app.get("/")
def root():
    return {
        "message": "Mock SCADA API for W&S Hydraulic Valve Replacement",
        "endpoints": {
            "/sensors": "Current live reading of all sensors",
            "/sensors/{name}": "Single sensor value",
            "/demo/loto": "POST - apply lockout/tagout (pressure bleeds to zero)",
            "/demo/anomaly": "POST - inject a random pressure anomaly (self-clears)",
            "/demo/reset": "POST - return to normal energized operation",
            "/demo/state": "GET - current demo state",
        },
    }


@app.get("/sensors", response_model=SensorReading)
def get_all_sensors():
    """Main endpoint the voice agent will call."""
    return generate_reading()


@app.get("/sensors/{sensor_name}")
def get_single_sensor(sensor_name: str):
    data = generate_reading().model_dump()
    if sensor_name not in data:
        return {"error": f"Unknown sensor: {sensor_name}"}
    return {
        "sensor": sensor_name,
        "value": data[sensor_name],
        "timestamp": data["timestamp"],
        "system_mode": data["system_mode"],
        "alarm": data["alarm"],
    }


# --------------------------- DEMO CONTROL ENDPOINTS -------------------------
@app.post("/demo/loto")
def demo_loto():
    with _lock:
        DEMO["mode"] = "draining"
        DEMO["mode_since"] = time.time()
    return {"ok": True, "mode": "draining"}


@app.post("/demo/anomaly")
def demo_anomaly(peak: Optional[float] = None, duration: Optional[float] = None):
    """Inject an anomaly. Magnitude and duration are randomised so the agent
    is reacting to genuinely live/unknown values, not a scripted constant."""
    with _lock:
        prev = DEMO["mode"]
        DEMO["return_mode"] = "energized" if prev == "energized" else "locked_out"
        DEMO["mode"] = "anomaly"
        DEMO["mode_since"] = time.time()
        DEMO["anomaly_peak"] = peak if peak is not None else round(random.uniform(205, 230), 1)
        DEMO["anomaly_duration"] = duration if duration is not None else round(random.uniform(2500, 3500), 1)
    return {
        "ok": True,
        "mode": "anomaly",
        "peak": DEMO["anomaly_peak"],
        "duration_s": DEMO["anomaly_duration"],
    }


@app.post("/demo/reset")
def demo_reset():
    with _lock:
        DEMO["mode"] = "energized"
        DEMO["mode_since"] = time.time()
    return {"ok": True, "mode": "energized"}


@app.get("/demo/state")
def demo_state():
    return DEMO


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("scada:app", host="0.0.0.0", port=8000, reload=True)