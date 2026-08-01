const windowSelect = document.getElementById("window-select");
const refreshBtn = document.getElementById("refresh-windows");
const intervalInput = document.getElementById("interval-input");
const intervalMinHint = document.getElementById("interval-min-hint");
const autoApproveToggle = document.getElementById("auto-approve-toggle");
const historyBody = document.querySelector("#history-table tbody");
const startBtn = document.getElementById("start-cycle-btn");
const stopBtn = document.getElementById("stop-cycle-btn");
const statusEl = document.getElementById("scheduler-status");
const countdownEl = document.getElementById("next-cycle-countdown");
const logEl = document.getElementById("log");
const ollamaResponseEl = document.getElementById("ollama-response");

const modal = document.getElementById("approval-modal");
const assessmentEl = document.getElementById("approval-assessment");
const detailsEl = document.getElementById("approval-details");
const approvalCountdownEl = document.getElementById("countdown-value");
const approveBtn = document.getElementById("approve-btn");
const denyBtn = document.getElementById("deny-btn");

const wsStatusEl = document.getElementById("ws-status");
const mcpStatusEl = document.getElementById("mcp-status");
const kpiNextCycle = document.getElementById("kpi-next-cycle");
const kpiConfidence = document.getElementById("kpi-confidence");
const kpiPnl = document.getElementById("kpi-pnl");
const kpiPositions = document.getElementById("kpi-positions");
const kpiTrend = document.getElementById("kpi-trend");
const kpiCountdown = document.getElementById("kpi-countdown");

let countdownTimer = null;
let currentCycleId = null;
let lastCapturePath = null;
let lastCaptureTime = 0;
let expandedResponse = false;
let countdownSeconds = 0;
let effectiveIntervalSeconds = 0;
let lastHistoryData = "";
let prerequisitesOk = false;
let currentProvider = "ollama";

async function fetchPrerequisites() {
  try {
    const res = await fetch("/api/health/prerequisites");
    const data = await res.json();
    prerequisitesOk = data.ok || false;
    updatePrerequisitesUI(data);
    return data;
  } catch (e) {
    console.error("Failed to fetch prerequisites:", e);
    prerequisitesOk = false;
    return { ok: false, ctrader: { running: false }, mcp: { reachable: false } };
  }
}

function updatePrerequisitesUI(data) {
  const ctraderEl = document.getElementById("prereq-ctrader");
  const mcpEl = document.getElementById("prereq-mcp");
  if (ctraderEl) {
    ctraderEl.textContent = data.ctrader?.running ? "cTrader: running" : "cTrader: not running";
    ctraderEl.className = "badge " + (data.ctrader?.running ? "connected" : "disconnected");
  }
  if (mcpEl) {
    mcpEl.textContent = data.mcp?.reachable ? "MCP: reachable" : "MCP: unreachable";
    mcpEl.className = "badge " + (data.mcp?.reachable ? "connected" : "disconnected");
  }
}

function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent += `[${ts}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function escapeHtml(str) {
  if (typeof str !== "string") return str;
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Sidebar navigation
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    const section = btn.dataset.section;
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    const target = document.getElementById(`section-${section}`);
    if (target) target.classList.add("active");
  });
});

function showOllamaResponse(parsed) {
  expandedResponse = false;
  const detailsEl = document.getElementById("ollama-details");
  const expandBtn = document.getElementById("ollama-expand-btn");
  const summaryEl = document.querySelector(".ollama-summary");

  const direction = parsed.trend_10min || "-";
  const confidence = parsed.confidence != null ? parsed.confidence : "-";
  const timeStr = new Date().toLocaleTimeString();

  const directionClass = direction === "up" ? "up" : direction === "down" ? "down" : "sideways";

  let html = `<div class="ollama-summary">`;
  if (lastCapturePath) {
    html += `<img class="ollama-thumbnail" src="/${lastCapturePath}" alt="Screenshot" />`;
  }
  html += `<span class="ollama-direction ${directionClass}">${direction}</span>`;
  html += `<span class="ollama-confidence">Confidence: ${confidence}</span>`;
  html += `<span class="ollama-time">${timeStr}</span>`;
  html += `</div>`;

  summaryEl.innerHTML = html;

  detailsEl.textContent = JSON.stringify(parsed, null, 2);
  detailsEl.classList.add("hidden");
  expandBtn.classList.remove("hidden");
  expandBtn.textContent = "▶ Expand";

  const thumbnail = document.querySelector(".ollama-thumbnail");
  if (thumbnail) {
    thumbnail.onclick = () => {
      const overlay = document.getElementById("ollama-screenshot-overlay");
      const img = document.getElementById("ollama-screenshot-img");
      img.src = thumbnail.src;
      overlay.classList.remove("hidden");
    };
  }
}

function hideOllamaOverlay() {
  document.getElementById("ollama-screenshot-overlay").classList.add("hidden");
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
  const minutes = parseInt(intervalInput.value, 10);
  if (intervalMinHint.dataset.minMinutes && minutes < parseInt(intervalMinHint.dataset.minMinutes, 10)) {
    log(`Interval too low: minimum is ${intervalMinHint.dataset.minMinutes} minutes (avg Ollama + 30s)`);
    intervalInput.value = intervalMinHint.dataset.minMinutes;
  }
  fetch(`/api/config/interval?minutes=${intervalInput.value}`, { method: "POST" });
};

async function updateIntervalHint() {
  try {
    const res = await fetch("/api/scheduler/timing");
    const data = await res.json();
    if (data.min_minutes) {
      const minMin = data.min_minutes;
      intervalInput.min = minMin;
      intervalMinHint.dataset.minMinutes = minMin;
      const avgMin = (data.avg_ollama_time_s / 60).toFixed(1);
      intervalMinHint.textContent = `Min: ${minMin} min (Ollama avg ${avgMin}min + 30s)`;
      effectiveIntervalSeconds = data.effective_interval_s;
    }
  } catch (e) {
    console.error("Failed to fetch timing info:", e);
  }
}

function startCountdown(seconds) {
  clearInterval(countdownTimer);
  countdownSeconds = seconds;
  updateCountdownDisplay();

  countdownTimer = setInterval(() => {
    countdownSeconds -= 1;
    if (countdownSeconds <= 0) {
      countdownSeconds = 0;
      updateCountdownDisplay();
      clearInterval(countdownTimer);
      countdownTimer = null;
    } else {
      updateCountdownDisplay();
    }
  }, 1000);
}

function updateCountdownDisplay() {
  if (countdownSeconds <= 0) {
    countdownEl.textContent = "";
    countdownEl.classList.add("hidden");
    if (kpiCountdown) kpiCountdown.textContent = "Waiting...";
    if (kpiNextCycle) kpiNextCycle.textContent = "--:--";
    return;
  }
  countdownEl.classList.remove("hidden");
  const mins = Math.floor(countdownSeconds / 60);
  const secs = countdownSeconds % 60;
  const text = `Next in ${mins}:${secs.toString().padStart(2, "0")}`;
  countdownEl.textContent = text;
  if (kpiCountdown) kpiCountdown.textContent = text;
  if (kpiNextCycle) kpiNextCycle.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
}

function stopCountdown() {
  clearInterval(countdownTimer);
  countdownTimer = null;
  countdownSeconds = 0;
  countdownEl.textContent = "";
  countdownEl.classList.add("hidden");
}

autoApproveToggle.onchange = () => {
  fetch(`/api/config/auto-approve?enabled=${autoApproveToggle.checked}`, { method: "POST" });
};

startBtn.onclick = async () => {
  log("Checking prerequisites...");
  const prereq = await fetchPrerequisites();
  if (!prereq.ok) {
    const reasons = [];
    if (!prereq.ctrader?.running) reasons.push("cTrader is not running");
    if (!prereq.mcp?.reachable) reasons.push("MCP server is not reachable");
    const msg = reasons.join("; ") + " — cannot start cycle.";
    log(msg);
    alert(msg);
    return;
  }
  log("Starting manual cycle...");
  statusEl.textContent = "Running";
  statusEl.classList.add("running");
  startCountdown(effectiveIntervalSeconds || 300);
  const res = await fetch("/api/scheduler/start", { method: "POST" });
  const data = await res.json();
  if (!data.ok) log(`Start failed: ${data.message}`);
};

stopBtn.onclick = async () => {
  log("Stopping scheduler...");
  statusEl.textContent = "Stopped";
  statusEl.classList.remove("running");
  stopCountdown();
  await fetch("/api/scheduler/stop", { method: "POST" });
};

function showApproval(cycleId, decision, timeoutS) {
  currentCycleId = cycleId;
  assessmentEl.textContent = decision.assessment;
  detailsEl.textContent = JSON.stringify(decision, null, 2);
  modal.classList.remove("hidden");

  let remaining = timeoutS;
  approvalCountdownEl.textContent = remaining;
  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    remaining -= 1;
    approvalCountdownEl.textContent = remaining;
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
  const cycleId = row.id ?? "-";
  const arrow = document.createElement("td");
  arrow.className = "history-arrow";
  arrow.textContent = "▶";

  let trendHtml = `<span class="trend-${row.trend || ""}">${row.trend ?? "-"}</span>`;
  let confidenceHtml = row.confidence != null ? `${Math.round(row.confidence * 100)}%` : "-";

  let actionHtml = row.action ?? "-";
  if (row.new_trade) {
    const t = row.new_trade;
    actionHtml = `${t.direction ?? ""} SL=${t.sl ?? ""} TP=${t.tp ?? ""}`.trim() || "-";
  }

  const statusClass = row.status ? `history-badge ${row.status}` : "";
  const statusHtml = row.status ? `<span class="${statusClass}">${row.status}</span>` : "-";

  tr.innerHTML = `
    ${arrow.outerHTML}
    <td>${ts}</td>
    <td>${trendHtml}</td>
    <td>${confidenceHtml}</td>
    <td>${actionHtml}</td>
    <td>${statusHtml}</td>
  `;

  const detailsTr = document.createElement("tr");
  detailsTr.className = "history-details";
  const screenshotSrc = row.screenshot_path ? `/${row.screenshot_path}` : "";
  const assessment = row.assessment ? row.assessment : "";
  const newTrade = row.new_trade ? true : false;
  const guardrail = row.guardrail_status ? true : false;
  const mcpResult = row.mcp_result ? true : false;

  detailsTr.innerHTML = `
    <td colspan="6">
      <div class="history-details-inner">
        <div class="history-meta">
          <p><span class="label">Date</span>${ts}</p>
          ${assessment ? `<p><span class="label">Assessment</span><br/>${escapeHtml(row.assessment)}</p>` : ""}
          ${newTrade ? `<p><span class="label">Trade</span><br/>${row.new_trade.direction} SL=${row.new_trade.sl} TP=${row.new_trade.tp}</p>` : ""}
          ${guardrail ? `<p><span class="label">Guardrail</span><br/>${row.guardrail_status}${row.guardrail_reason ? ` — ${escapeHtml(row.guardrail_reason)}` : ""}</p>` : ""}
          ${mcpResult ? `<p><span class="label">MCP Result</span><br/><pre>${JSON.stringify(row.mcp_result, null, 2)}</pre></p>` : ""}
          <p><span class="label">Cycle ID</span> #${cycleId}</p>
        </div>
        ${screenshotSrc ? `<img class="history-thumb" src="${screenshotSrc}" alt="Screenshot" />` : ""}
      </div>
    </td>
  `;

  const arrowCell = tr.querySelector(".history-arrow");
  arrowCell.onclick = () => {
    const isOpen = detailsTr.classList.toggle("open");
    arrowCell.textContent = isOpen ? "▼" : "▶";
  };

  const thumb = detailsTr.querySelector(".history-thumb");
  if (thumb) {
    thumb.onclick = () => {
      const overlay = document.getElementById("ollama-screenshot-overlay");
      const img = document.getElementById("ollama-screenshot-img");
      img.src = thumb.src;
      overlay.classList.remove("hidden");
    };
  }

  historyBody.append(detailsTr);
  historyBody.append(tr);
}

async function loadHistory() {
  const res = await fetch("/api/history");
  const rows = await res.json();
  const dataKey = JSON.stringify(rows);
  if (dataKey === lastHistoryData) {
    return;
  }
  lastHistoryData = dataKey;
  historyBody.innerHTML = "";
  rows.forEach(r => {
    let response = {};
    try { response = JSON.parse(r.model_response || "{}"); } catch (e) {}
    let mcpResult = {};
    try { mcpResult = JSON.parse(r.mcp_result || "{}"); } catch (e) {}
    addHistoryRow({
      id: r.id,
      ts: r.ts,
      screenshot_path: r.screenshot_path,
      trend: response.trend_10min,
      confidence: response.confidence,
      assessment: response.assessment,
      action: response.open_position_action || (response.new_trade ? "new_trade" : "-"),
      new_trade: response.new_trade,
      status: r.action_status,
      guardrail_status: r.guardrail_status,
      guardrail_reason: r.guardrail_reason,
      mcp_result: mcpResult,
    });
  });
}

const ws = new WebSocket(`ws://${location.host}/ws`);
let reconnectTimer = null;

function updateWsStatus(status, className) {
  if (!wsStatusEl) return;
  wsStatusEl.textContent = status;
  wsStatusEl.className = "badge " + (className || "");
}

function updateMcpStatus(connected) {
  if (!mcpStatusEl) return;
  if (connected) {
    mcpStatusEl.textContent = "MCP: connected";
    mcpStatusEl.className = "badge connected";
  } else {
    mcpStatusEl.textContent = "MCP: offline";
    mcpStatusEl.className = "badge disconnected";
  }
}

function connectWs() {
  updateWsStatus("WS: connecting...", "");
  ws.onopen = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    updateWsStatus("WS: connected", "connected");
  };
  ws.onmessage = (evt) => {
    const { type, payload } = JSON.parse(evt.data);
    if (type === "cycle_start") {
      ollamaResponseEl.textContent = "Analyzing...";
      startCountdown(effectiveIntervalSeconds || 300);
      statusEl.textContent = "Running";
      statusEl.classList.add("running");
    }
    if (type === "approval_requested") {
      showApproval(payload.cycle_id, payload.decision, payload.timeout_s);
    }
    if (["executed", "denied", "auto_denied_timeout", "guardrail_rejected", "no_action"].includes(type)) {
      loadHistory();
      startCountdown(effectiveIntervalSeconds || 300);
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
        showOllamaResponse(parsed);
      } catch {
        ollamaResponseEl.textContent = String(payload.response);
      }
      log("Ollama response received and displayed");
      loadHistory();
    }
    if (type === "capture") {
      const now = Date.now();
      if (payload.path !== lastCapturePath || now - lastCaptureTime > 2000) {
        log(`Screenshot captured: ${payload.path}`);
        lastCapturePath = payload.path;
        lastCaptureTime = now;
      }
    }
    if (type === "mcp_connect_ok") {
      updateMcpStatus(true);
    }
    if (type === "mcp_connect_retry" || type === "mcp_call_error") {
      updateMcpStatus(false);
    }
  };
  ws.onclose = () => {
    updateWsStatus("WS: disconnected — reconnecting...", "disconnected");
    reconnectTimer = setTimeout(connectWs, 3000);
  };
  ws.onerror = () => {
    updateWsStatus("WS: error — reconnecting...", "disconnected");
    ws.close();
  };
}
connectWs();

document.getElementById("ollama-expand-btn").onclick = () => {
  const detailsEl = document.getElementById("ollama-details");
  const expandBtn = document.getElementById("ollama-expand-btn");
  if (expandedResponse) {
    detailsEl.classList.add("hidden");
    expandBtn.textContent = "▶ Expand";
    expandedResponse = false;
  } else {
    detailsEl.classList.remove("hidden");
    expandBtn.textContent = "▼ Collapse";
    expandedResponse = true;
  }
};

document.getElementById("ollama-screenshot-close").onclick = hideOllamaOverlay;

loadWindows();
loadHistory();
updateIntervalHint();
fetchPrerequisites();
setInterval(fetchPrerequisites, 30000);

const providerSelect = document.getElementById("setting-provider");
const nvidiaSettings = document.getElementById("nvidia-settings");
if (providerSelect) {
  providerSelect.onchange = () => {
    currentProvider = providerSelect.value;
    if (nvidiaSettings) {
      nvidiaSettings.classList.toggle("hidden", currentProvider !== "nvidia");
    }
  };
}

// Settings page handlers
const saveSettingsBtn = document.getElementById("save-settings-btn");
if (saveSettingsBtn) {
  saveSettingsBtn.onclick = async () => {
    const patches = {};

    const symbol = document.getElementById("setting-symbol")?.value;
    const pip = document.getElementById("setting-pip")?.value;
    if (symbol || pip) {
      patches.trading = {};
      if (symbol) patches.trading.default_symbol = symbol;
      if (pip) patches.trading.pip_size = parseFloat(pip);
    }

    const maxLoss = document.getElementById("setting-max-loss")?.value;
    const maxPositions = document.getElementById("setting-max-positions")?.value;
    const minSl = document.getElementById("setting-min-sl")?.value;
    if (maxLoss || maxPositions || minSl) {
      patches.risk_limits = {};
      if (maxLoss) patches.risk_limits.max_daily_loss_pct = parseFloat(maxLoss);
      if (maxPositions) patches.risk_limits.max_concurrent_positions = parseInt(maxPositions, 10);
      if (minSl) patches.risk_limits.min_sl_distance_pips = parseInt(minSl, 10);
    }

    const provider = document.getElementById("setting-provider")?.value;
    if (provider) {
      patches.provider = provider;
      currentProvider = provider;
    }

    const nvidiaModel = document.getElementById("setting-nvidia-model")?.value;
    if (nvidiaModel) {
      patches.nvidia = patches.nvidia || {};
      patches.nvidia.model = nvidiaModel;
    }

    const nvidiaApiKey = document.getElementById("setting-nvidia-api-key")?.value;
    if (nvidiaApiKey) {
      patches.nvidia = patches.nvidia || {};
      patches.nvidia.api_key = nvidiaApiKey;
    }

    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patches),
    });

    log("Configuration saved");
    alert("Configuration saved successfully.");
  };
}
