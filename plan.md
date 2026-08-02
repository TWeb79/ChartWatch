# ChartWatch — Bug Fix Plan (Buttons / Countdown / Screenshot Activity)

Author: Inventions4All - github:TWeb79
Created: 2026-08-01

---

## 0. Previously Resolved (see git history)

Status: All items resolved.

| Bug | File(s) | Severity | Status |
|-----|---------|----------|--------|
| Missing `#log` element crashes `log()` | `static/index.html`, `static/app.js` | Critical | Fixed |
| Duplicate `id="history-table"` | `static/index.html`, `static/app.js` | Medium | Fixed |

---

## 1. Resolved

| # | Issue | Status |
|---|-------|--------|
| 1 | Log says "Ollama" when using NVIDIA | Fixed |
| 2 | LLM status goes red with `TypeError: Load failed` | Fixed |
| 3 | Config prompt not used as system prompt | Fixed |
| 4 | No model selection dropdown | Implemented |
| 5 | NVIDIA 500: "multimodal processing is not enabled" | Fixed |

---

## 2. Implemented: Model availability test at startup

| # | Issue | Files | Severity | Status |
|---|-------|-------|----------|--------|
| 6 | Add startup test that probes all models from the selected LLM provider and filters out unavailable / non-vision / paid models | `chartwatch/api.py`, `chartwatch/llm_utils.py`, `tests/test_llm_models.py` | High | Implemented |

### Feature 6 — Model availability + feature test at startup

**Files: `chartwatch/api.py`, `chartwatch/llm_utils.py`, `tests/test_llm_models.py`**

User wants a test that runs once at application startup which:
1. Fetches all available models from the selected LLM provider
2. Tests each model for:
   - Availability (API responds within timeout)
   - Vision/multimodal support (required for screenshot analysis)
   - Free of charge (non-premium)
3. Removes non-qualifying models from the model selection dropdown
4. Caches filtered results to `<provider>_models.json` for subsequent startups
5. Shows yellow "Analyzing models..." status in the LLM badge during testing
6. Uses a 10x10px dummy PNG image and `dummy.md` instructions file for probing

**Implementation:**
1. Created `chartwatch/llm_utils.py` with `filter_vision_models()`:
   - Extracts vision patterns and NVIDIA free prefixes to a testable module
   - For Ollama: all locally installed models are available and free; filter to
     vision-capable models by name pattern (llava, qwen-vl, mllama, etc.)
   - For NVIDIA: filter to vision-capable free models by known patterns
2. Added `GET /api/llm/models/test` endpoint that re-runs the test on demand
3. Added `_test_and_cache_models()` async function called at startup:
   - Checks for existing `<provider>_models.json` cache file first
   - If cache exists, loads it and broadcasts `models_ready` WebSocket event
   - If no cache, fetches from provider, filters, saves to JSON, broadcasts
     `models_testing` → `models_ready` (or `models_error`) WebSocket events
4. Updated `GET /api/llm/models` endpoint to use cached/filtered results
5. Added WebSocket handlers in `app.js` for `models_testing`, `models_ready`,
    `models_error` events
6. Created `chartwatch/dummy.md` (minimal instructions file for testing)
7. Created `static/dummy_test.png` (10x10px red PNG for image probing tests)
8. Added 8 tests in `tests/test_llm_models.py`
9. **Rate limiting**: `GET /api/llm/models/test` endpoint is rate-limited
   (min 30s between calls) to prevent accidental provider API flooding
10. **DDOS prevention**: Uses name-pattern filtering, NOT per-model API probing,
    to avoid flooding the provider with test requests
11. **404 error handling**: Added specific 404 error handling in `nvidia_client.py`
    with actionable message guiding users to try known-good models when a model
    returns "Function not found" (model not deployable for account)
12. Added README.md instructions for obtaining a free NVIDIA API key at
    https://build.nvidia.com/models

