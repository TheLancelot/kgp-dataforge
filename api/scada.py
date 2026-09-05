from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import math
import time
import random
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
    notes: str = ""

# Global state so values evolve smoothly
start_time = time.time()

def generate_reading() -> SensorReading:
    t = time.time() - start_time

    # Base fluctuating signals (smooth + a bit of noise)
    hydraulic = 120 + 25 * math.sin(t * 0.15) + random.uniform(-3, 3)
    temp = 55 + 12 * math.sin(t * 0.08 + 1) + random.uniform(-1.5, 1.5)
    accumulator = 130 + 15 * math.sin(t * 0.12) + random.uniform(-2, 2)
    roll_pos = 22 + 4 * math.sin(t * 0.25) + random.uniform(-0.8, 0.8)
    stroke = 48 + 18 * math.sin(t * 0.18) + random.uniform(-2, 2)

    # Clamp to realistic ranges
    hydraulic = max(0, min(180, hydraulic))
    temp = max(25, min(110, temp))
    accumulator = max(50, min(180, accumulator))
    roll_pos = max(0, min(50, roll_pos))
    stroke = max(0, min(100, stroke))

    # Occasional anomaly injection (for demo / testing)
    # Uncomment one of these when you want to force an anomaly during demo
    # hydraulic = 40.0          # stuck pressure anomaly
    # temp = 98.0               # too hot
    # roll_pos = 38.5           # creeping down
    # profibus = "FAULT"

    profibus = "OK"
    notes = "Normal operation"

    # Small random chance of a soft anomaly (optional)
    if random.random() < 0.03:
        notes = "Minor fluctuation detected"

    return SensorReading(
        timestamp=time.time(),
        hydraulic_pressure_bar=round(hydraulic, 1),
        manifold_temperature_c=round(temp, 1),
        accumulator_pressure_bar=round(accumulator, 1),
        pinch_roll_position_mm=round(roll_pos, 2),
        valve_stroke_percent=round(stroke, 1),
        profibus_status=profibus,
        notes=notes,
    )

@app.get("/")
def root():
    return {
        "message": "Mock SCADA API for W&S Hydraulic Valve Replacement",
        "endpoints": {
            "/sensors": "Current live reading of all sensors",
            "/sensors/{name}": "Single sensor value",
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
    }

# Optional: force anomaly endpoints (useful during demo)
@app.post("/demo/force_pressure_stuck")
def force_pressure_stuck():
    # This is just a simple way to inject for demo.
    # In real use you can make the generate_reading() look at a global flag.
    return {"message": "In a real demo you would set a global flag here"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("scada:app", host="0.0.0.0", port=8000, reload=True)