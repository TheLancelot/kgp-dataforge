
    const API_URL = "http://localhost:8000/sensors";

    function setBadge(el, level) {
      el.className = "badge " + level;
      el.textContent = level === "ok" ? "Normal" : level === "warn" ? "Warning" : "Danger";
    }

    function updateBar(barEl, percent, color) {
      barEl.style.width = Math.min(100, Math.max(0, percent)) + "%";
      barEl.style.background = color;
    }

    function getPressureStatus(val) {
      if (val < 20 || val > 160) return "danger";
      if (val < 40 || val > 150) return "warn";
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
          (data.hydraulic_pressure_bar / 180) * 100,
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

        document.getElementById("notesValue").textContent = data.notes || "—";

        const ts = new Date(data.timestamp * 1000);
        document.getElementById("lastUpdate").textContent = ts.toLocaleTimeString();

      } catch (err) {
        document.getElementById("errorBox").style.display = "block";
        document.getElementById("connectionStatus").textContent = "Disconnected";
        document.getElementById("liveDot").style.background = "var(--red)";
      }
    }

    // Initial load + poll every second
    fetchData();
    setInterval(fetchData, 1000);