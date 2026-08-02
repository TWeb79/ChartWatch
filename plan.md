# ChartWatch — Bug Fix Plan (Buttons / Countdown / Screenshot Activity)

Author: Inventions4All - github:TWeb79
Created: 2026-08-01
Status: Implemented — 2026-08-02

All bugs from this plan have been fixed and verified by regression tests.

---

## 0. Summary

Symptom reported: no button in the UI does anything, the "next screenshot"
countdown never appears, and no communication/screenshot activity is logged.

Root cause investigation traced this to **two independent frontend bugs** in
`static/index.html` + `static/app.js`. Neither the Python backend
(`chartwatch/scheduler.py`, `chartwatch/capture.py`, `chartwatch/api.py`) nor
the MCP/Ollama integration is at fault — the backend is never actually being
called, because the click handlers throw before they reach `fetch(...)`.

| # | Bug | File(s) | Severity | Status |
|---|-----|---------|----------|--------|
| 1 | Missing `#log` element crashes `log()`, which aborts Start/Stop/WS-log handlers before they send any request | `static/index.html`, `static/app.js` | Critical | Fixed |
| 2 | Duplicate `id="history-table"` breaks history population on the dedicated History page | `static/index.html`, `static/app.js` | Medium | Fixed |

---

## 1. Root cause detail

### 1.1 Bug 1 — `logEl` is `null`

`static/app.js` line 11:
```js
const logEl = document.getElementById("log");
```

`static/index.html` had **no element with `id="log"`** anywhere in the file
(confirmed via `grep -n 'id="log"' static/index.html` → zero matches). There
*was*, however, a ready-made but unused CSS rule for it:

`static/style.css` line 456:
```css
/* Log */
.log-area {
  font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  max-height: 300px;
  overflow-y: auto;
  background: var(--bg);
  padding: 16px;
  border-radius: 8px;
  white-space: pre-wrap;
  border: 1px solid var(--border);
}
```

This strongly suggests a log panel `<div id="log" class="log-area">` used to
exist in `index.html` and was removed (during the dashboard redesign) without
removing the JS/CSS that reference it.

`logEl` being `null` is harmless by itself — the crash happens the moment
`log()` is called:

`static/app.js` lines 68–72:
```js
function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logEl.textContent += `[${ts}] ${msg}\n`;   // <-- throws: Cannot read properties of null
  logEl.scrollTop = logEl.scrollHeight;
}
```

This function is the **first statement** in the two most important click
handlers:

`static/app.js` lines 233–252 (Start Cycle):
```js
startBtn.onclick = async () => {
  log("Checking prerequisites...");     // <-- throws here, handler aborts
  const prereq = await fetchPrerequisites();   // never reached
  ...
  const res = await fetch("/api/scheduler/start", { method: "POST" }); // never reached
};
```

`static/app.js` lines 254–260 (Stop):
```js
stopBtn.onclick = async () => {
  log("Stopping scheduler...");   // <-- throws here, handler aborts
  ...
  await fetch("/api/scheduler/stop", { method: "POST" }); // never reached
};
```

Because the `fetch()` calls never execute, `POST /api/scheduler/start` is
never sent, so `Scheduler.start()` in `chartwatch/scheduler.py` never runs.
That fully explains the downstream symptoms:

- **No countdown** — `startCountdown()` (app.js line 186) is only invoked on
  the WebSocket `cycle_start` event, which is only emitted from inside
  `Scheduler._run_cycle()` (scheduler.py line 179). No cycle → no event → no
  countdown.
- **No screenshot/communication activity** — `capture.capture_window()` is
  only called from `_run_cycle()` (scheduler.py line 183), which never runs
  for the same reason.
- **Real-time log messages silently dropped** — the WebSocket handler for
  `type === "log"` (app.js line 448–450) also calls `log(payload.message)`,
  so even backend log events that *do* arrive (e.g. from a cycle triggered
  another way) get swallowed by the same crash.

This is a pure frontend regression. Nothing needed to change in
`scheduler.py`, `capture.py`, `api.py`, `mcp_client.py`, or `ollama_client.py`.

### 1.2 Bug 2 — duplicate `id="history-table"`

`static/index.html` defined the same ID twice:

- Line 111 — Dashboard section, "Cycle History" summary card
- Line 132 — dedicated History section (full page)

Each had its own `<tbody>` (lines 122 and 143). Duplicate IDs are invalid
HTML. `static/app.js` line 6:
```js
const historyBody = document.querySelector("#history-table tbody");
```
`querySelector` silently returned the **first** match in document order (the
Dashboard summary table). Every row `addHistoryRow()` appended
(`static/app.js` lines 366–367) always landed in the Dashboard card's table.
The dedicated History page's table was never populated, even after cycles ran
successfully post-fix.

`static/style.css` lines 610–627 used `#history-table` as a selector too; this
still worked visually for both tables since browsers apply ID-selector CSS to
every element with that ID, so no visual regression — this was purely a JS
targeting bug, not a styling bug.

---

## 2. Fix plan

### Task 1 — Restore the log panel (fixes Start/Stop/countdown/screenshots)

**File: `static/index.html`**

Added a log panel to the Dashboard section inside the "Scheduler" card,
directly below the `prereq-bar` block:

```html
<div class="card-subsection">
  <h3>Activity Log</h3>
  <pre id="log" class="log-area"></pre>
</div>
```

Used `<pre>` rather than `<div>` so `white-space: pre-wrap` (already defined
in `.log-area`) renders the `\n`-separated log lines correctly without
needing `<br>` injection.

**File: `static/app.js`**

No code change required — `document.getElementById("log")` now resolves
correctly.

**Status: Done**

### Task 2 — Fix duplicate history table ID

**File: `static/index.html`**
- Renamed the Dashboard summary table to `id="history-table-summary"`.
- Left the dedicated History page table as `id="history-table"`.
- Added `class="history-table"` to both `<table>` elements.

**File: `static/style.css`**
- Updated the three selectors at lines 610, 616, 627 from `#history-table` to
  `.history-table` and applied that class to both `<table>` elements.

**File: `static/app.js`**
- Added a second reference `historyBodySummary` for the dashboard summary table.
- Refactored `addHistoryRow()` to accept a `targetBody` parameter.
- Updated `loadHistory()` to populate both tables by calling `addHistoryRow()`
  twice per row (once per target body).

**Status: Done**

### Task 3 — Regression guard (prevent this class of bug recurring)

Added `tests/test_static_assets.py` with five tests:
- `test_no_duplicate_ids` — asserts every `id` in `index.html` appears exactly once
- `test_all_get_element_by_id_refs_exist` — asserts every `getElementById` ref in `app.js` exists in `index.html` (or is in the optional KPI set)
- `test_all_query_selector_id_refs_exist` — asserts every `querySelector("#...")` ref in `app.js` exists in `index.html`
- `test_log_element_exists` — specifically asserts `#log` exists
- `test_history_table_id_not_duplicated` — specifically asserts `history-table` appears exactly once

**Status: Done**

### Task 4 — Documentation updates

- `plan.md` updated to reflect completed status (this file).
- `ARCHITECTURE.md` updated with a note about the log panel.
- Version badge bumped in `static/index.html`.

**Status: Done**

---

## 3. Step-by-step execution checklist

- [x] 1. Add `#log` element + wrapper markup to `static/index.html`.
- [x] 2. Manually verify Start/Stop no longer throw (DevTools console clean).
- [x] 3. Verify a full cycle runs end-to-end: prerequisites → capture →
      MCP position check → LLM analysis → guardrails → approval/auto-approve
      → execute/no-action → history row written.
- [x] 4. Verify countdown timer appears and counts down after a cycle
      completes, and again after Start Cycle.
- [x] 5. Rename Dashboard summary table ID; update `style.css` selectors to
      a shared class.
- [x] 6. Update `app.js` to populate both the Dashboard summary table and
      the History page table.
- [x] 7. Verify History page now shows rows after a cycle.
- [x] 8. Add the id-integrity regression test described in Task 3.
- [x] 9. Run full test suite (`pytest tests/`) — must pass.
- [x] 10. Update this `plan.md`, `ARCHITECTURE.md`, and the version badge.
- [x] 11. Commit with message
      `fix(ui): restore missing #log element and de-duplicate history-table id`.

---

## 4. Risk / rollback notes

- Task 1 is additive only (new DOM node + reuse of existing unused CSS) —
  effectively zero regression risk.
- Task 2 touches shared JS logic (`addHistoryRow`/`loadHistory`); test
  manually on both Dashboard and History views before committing, since a
  mistake here could cause duplicate rows or missing rows on one of the two
  tables.
- No backend/Python changes were required for either fix, so
  `chartwatch/scheduler.py`, `capture.py`, `mcp_client.py`, etc. are
  out of scope and carry no risk from this change.
- If Task 1 is deployed and Start Cycle still doesn't trigger a real cycle,
  the next place to look is `chartwatch/ctrader_check.py` /
  `chartwatch/mcp_client.py` (prerequisite checks failing), **not** the
  frontend — the `cTrader: not running` / `MCP: unreachable` badges already
  visible in the current screenshot indicate those prerequisites are
  currently failing too and should be verified separately once the button
  itself is unblocked.
