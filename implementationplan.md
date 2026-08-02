# ChartWatch Implementation Plan
Author: Inventions4All - github:TWeb79  
Last updated: 2026-08-02T12:22

## All Implemented — 81 tests passing

### Bug Fixes
1. **Timeout kwarg error** — `timeout` moved from `client.chat()` to `ollama.Client()` constructor
2. **Wrong account balance** — `mcp_accounts()` reads balance from accounts list for selected account
3. **NVIDIA wrong model (qwen3.5:9b)** — Model resolution is now per-provider in `llm_client.py`
4. **Instruction file not passed to NVIDIA** — Added `instruction_file: tradingview.md` to nvidia config
5. **NVIDIA screenshot not reaching model** — Changed from Ollama-style `"images"` key to
   OpenAI-compatible `content` array with `image_url` blocks

### Features
6. **LLM status icon** — `#llm-status` badge in header + `/api/health/llm` endpoint
7. **Account balance refresh** — On startup, MCP click, and screenshot capture (WS `capture` event)
8. **Account balance → LLM prompt** — `get_account_balance()` in MCP client; scheduler fetches
   balance after screenshot, passes to both LLM clients, includes in prompt; used for guardrails
9. **Configurable timeout per provider** — `ollama.timeout: 120` and `nvidia.timeout: 30` in
   config.yaml, passed through the full call chain

### Cleanup
10. **Deleted** obsolete `.kilo/plans/1785657535999-ctrader-account-selector.md`

### Test coverage (81 total)
- 5 ollama client tests
- 5 NVIDIA client tests (incl. OpenAI image format + balance in prompt)
- 8 LLM dispatch tests (model resolution, timeout, instruction file, account balance)
- 3 LLM health endpoint tests
- 4 MCP accounts tests
- + 61 pre-existing tests
