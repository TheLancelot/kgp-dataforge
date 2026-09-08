const BASE_URL = "http://localhost:8000";
const API_URL = BASE_URL + "/sensors";
const PRESSURE_MAX = 250;

function setBadge(el, level) {
  el.className = "badge " + level;
  el.textContent = level === "ok" ? "Normal" : level === "warn" ? "Warning" : "Danger";
}

function updateBar(barEl, percent, color) {
  barEl.style.width = Math.min(100, Math.max(0, percent)) + "%";
  barEl.style.background = color;
}

function getPressureStatus(val) {
  if (val > 195) return "danger";
  if (val > 188) return "warn";
  return "ok";
}

function getTempStatus(val) {
  if (val > 90) return "danger";
  if (val > 75) return "warn";
  return "ok";
}

function getRollStatus(val) {
  if (val > 40) return "danger";
  if (val > 32) return "warn";
  return "ok";
}

function applyMode(mode, alarm) {
  const pill = document.getElementById("modePill");
  const modeEl = document.getElementById("systemMode");
  const modeVal = document.getElementById("systemModeVal");

  const pretty = (mode || "--").replace(/_/g, " ");
  modeEl.textContent = pretty;
  modeVal.textContent = pretty;

  pill.classList.remove("mode-ok", "mode-warn", "mode-danger");
  if (alarm || mode === "ALARM") {
    pill.classList.add("mode-danger");
    modeVal.style.color = "var(--red)";
  } else if (mode === "LOCKED_OUT" || mode === "LOCKOUT_IN_PROGRESS") {
    pill.classList.add("mode-warn");
    modeVal.style.color = "var(--yellow)";
  } else {
    pill.classList.add("mode-ok");
    modeVal.style.color = "var(--green)";
  }
}

async function fetchData() {
  try {
    const res = await fetch(API_URL);
    if (!res.ok) throw new Error("API error");
    const data = await res.json();

    document.getElementById("errorBox").style.display = "none";
    document.getElementById("connectionStatus").textContent = "Live";
    document.getElementById("liveDot").style.background = "var(--green)";

    // Pressure
    document.getElementById("pressureValue").textContent = data.hydraulic_pressure_bar.toFixed(1);
    const pStatus = getPressureStatus(data.hydraulic_pressure_bar);
    setBadge(document.getElementById("pressureBadge"), pStatus);
    updateBar(
      document.getElementById("pressureBar"),
      (data.hydraulic_pressure_bar / PRESSURE_MAX) * 100,
      pStatus === "danger" ? "var(--red)" : pStatus === "warn" ? "var(--yellow)" : "var(--green)"
    );

    // Temperature
    document.getElementById("tempValue").textContent = data.manifold_temperature_c.toFixed(1);
    const tStatus = getTempStatus(data.manifold_temperature_c);
    setBadge(document.getElementById("tempBadge"), tStatus);
    updateBar(
      document.getElementById("tempBar"),
      ((data.manifold_temperature_c - 25) / 85) * 100,
      tStatus === "danger" ? "var(--red)" : tStatus === "warn" ? "var(--yellow)" : "var(--green)"
    );

    // Accumulator
    document.getElementById("accValue").textContent = data.accumulator_pressure_bar.toFixed(1);
    updateBar(document.getElementById("accBar"), (data.accumulator_pressure_bar / 180) * 100, "var(--blue)");

    // Pinch Roll
    document.getElementById("rollValue").textContent = data.pinch_roll_position_mm.toFixed(2);
    const rStatus = getRollStatus(data.pinch_roll_position_mm);
    setBadge(document.getElementById("rollBadge"), rStatus);
    updateBar(
      document.getElementById("rollBar"),
      (data.pinch_roll_position_mm / 50) * 100,
      rStatus === "danger" ? "var(--red)" : rStatus === "warn" ? "var(--yellow)" : "var(--blue)"
    );

    // Valve Stroke
    document.getElementById("strokeValue").textContent = data.valve_stroke_percent.toFixed(1);
    updateBar(document.getElementById("strokeBar"), data.valve_stroke_percent, "var(--blue)");

    // Status
    const profibusEl = document.getElementById("profibusValue");
    profibusEl.textContent = data.profibus_status;
    profibusEl.style.color = data.profibus_status === "OK" ? "var(--green)" : "var(--red)";

    const notesEl = document.getElementById("notesValue");
    notesEl.textContent = data.notes || "—";
    notesEl.style.color = data.alarm ? "var(--red)" : "var(--text)";

    applyMode(data.system_mode, data.alarm);

    const ts = new Date(data.timestamp * 1000);
    document.getElementById("lastUpdate").textContent = ts.toLocaleTimeString();

  } catch (err) {
    document.getElementById("errorBox").style.display = "block";
    document.getElementById("connectionStatus").textContent = "Disconnected";
    document.getElementById("liveDot").style.background = "var(--red)";
  }
}

async function postDemo(path) {
  try {
    await fetch(BASE_URL + path, { method: "POST" });
    fetchData();
  } catch (e) {
    console.error("Demo control failed", e);
  }
}

// Wire up demo buttons
document.getElementById("btnLoto").addEventListener("click", () => postDemo("/demo/loto"));
document.getElementById("btnAnomaly").addEventListener("click", () => postDemo("/demo/anomaly"));
document.getElementById("btnReset").addEventListener("click", () => postDemo("/demo/reset"));

// Initial load + poll every second
fetchData();
setInterval(fetchData, 1000);