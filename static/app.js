const windowSelect = document.getElementById("window-select");
const refreshBtn = document.getElementById("refresh-windows");
const intervalInput = document.getElementById("interval-input");
const autoApproveToggle = document.getElementById("auto-approve-toggle");
const historyBody = document.querySelector("#history-table tbody");
const startBtn = document.getElementById("start-cycle-btn");
const stopBtn = document.getElementById("stop-cycle-btn");
const statusEl = document.getElementById("scheduler-status");
const logEl = document.getElementById("log");
const ollamaResponseEl = document.getElementById("ollama-response");

const modal = document.getElementById("approval-modal");
const assessmentEl = document.getElementById("approval-assessment");
const detailsEl = document.getElementById("approval-details");
const countdownEl = document.getElementById("countdown-value");
const approveBtn = document.getElementById("approve-btn");
const denyBtn = document.getElementById("deny-btn");

let countdownTimer = null;
let currentCycleId = null;

function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent += `[${ts}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

async function loadWindows() {
  const res = await fetch("/api/windows");
  const windows = await res.json();
  windowSelect.innerHTML = "";
  windows.forEach(w => {
    const opt = document.createElement("option");
    opt.value = w.id;
    opt.textContent = `${w.owner} — ${w.title}`;
    windowSelect.appendChild(opt);
  });
}

refreshBtn.onclick = loadWindows;

windowSelect.onchange = () => {
  const opt = windowSelect.selectedOptions[0];
  fetch(`/api/config/target-window?window_id=${opt.value}&title=${encodeURIComponent(opt.textContent)}`, {
    method: "POST",
  });
};

intervalInput.onchange = () => {
  fetch(`/api/config/interval?minutes=${intervalInput.value}`, { method: "POST" });
};

autoApproveToggle.onchange = () => {
  fetch(`/api/config/auto-approve?enabled=${autoApproveToggle.checked}`, { method: "POST" });
};

startBtn.onclick = async () => {
  log("Starting manual cycle...");
  statusEl.textContent = "Running";
  statusEl.style.color = "var(--green)";
  const res = await fetch("/api/scheduler/start", { method: "POST" });
  const data = await res.json();
  if (!data.ok) log(`Start failed: ${data.message}`);
};

stopBtn.onclick = async () => {
  log("Stopping scheduler...");
  statusEl.textContent = "Stopped";
  statusEl.style.color = "var(--red)";
  await fetch("/api/scheduler/stop", { method: "POST" });
};

function showApproval(cycleId, decision, timeoutS) {
  currentCycleId = cycleId;
  assessmentEl.textContent = decision.assessment;
  detailsEl.textContent = JSON.stringify(decision, null, 2);
  modal.classList.remove("hidden");

  let remaining = timeoutS;
  countdownEl.textContent = remaining;
  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    remaining -= 1;
    countdownEl.textContent = remaining;
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      hideApproval();
    }
  }, 1000);
}

function hideApproval() {
  modal.classList.add("hidden");
  clearInterval(countdownTimer);
  currentCycleId = null;
}

approveBtn.onclick = () => {
  if (currentCycleId != null) fetch(`/api/approve/${currentCycleId}`, { method: "POST" });
  hideApproval();
};

denyBtn.onclick = () => {
  if (currentCycleId != null) fetch(`/api/deny/${currentCycleId}`, { method: "POST" });
  hideApproval();
};

function addHistoryRow(row) {
  const tr = document.createElement("tr");
  const ts = row.ts ? new Date(row.ts * 1000).toLocaleTimeString() : "-";
  tr.innerHTML = `
    <td>${ts}</td>
    <td>${row.trend ?? "-"}</td>
    <td>${row.confidence ?? "-"}</td>
    <td>${row.action ?? "-"}</td>
    <td>${row.status ?? "-"}</td>
  `;
  historyBody.prepend(tr);
}

async function loadHistory() {
  const res = await fetch("/api/history");
  const rows = await res.json();
  historyBody.innerHTML = "";
  rows.forEach(r => {
    let response = {};
    try { response = JSON.parse(r.model_response || "{}"); } catch (e) {}
    addHistoryRow({
      trend: response.trend_10min,
      confidence: response.confidence,
      action: response.open_position_action || (response.new_trade ? "new_trade" : "-"),
      status: r.action_status,
    });
  });
}

const ws = new WebSocket(`ws://${location.host}/ws`);
let reconnectTimer = null;

function connectWs() {
  ws.onopen = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };
  ws.onmessage = (evt) => {
    const { type, payload } = JSON.parse(evt.data);
    if (type === "approval_requested") {
      showApproval(payload.cycle_id, payload.decision, payload.timeout_s);
    }
    if (["executed", "denied", "auto_denied_timeout", "guardrail_rejected", "no_action"].includes(type)) {
      loadHistory();
    }
    if (type === "auto_denied_timeout") {
      hideApproval();
    }
    if (type === "log") {
      log(payload.message);
    }
    if (type === "model_response") {
      try {
        const parsed = typeof payload.response === "string" ? JSON.parse(payload.response) : payload.response;
        ollamaResponseEl.textContent = JSON.stringify(parsed, null, 2);
      } catch {
        ollamaResponseEl.textContent = String(payload.response);
      }
    }
    if (type === "cycle_start") {
      log("Cycle started");
      ollamaResponseEl.textContent = "Waiting for response...";
    }
    if (type === "capture") {
      log(`Screenshot captured: ${payload.path}`);
    }
  };
  ws.onclose = () => {
    reconnectTimer = setTimeout(connectWs, 3000);
  };
  ws.onerror = () => {
    ws.close();
  };
}
connectWs();

loadWindows();
loadHistory();
