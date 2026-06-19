# health-agent

A personal health agent that tracks what you eat, the supplements you take, and the conditions you live with — and gives suggestions that are checked against your profile before you see them.

Built as a Session 5 / `llm_gatewayV2` showcase: native tool-use, prompt caching, reasoning levels, structured output, and capability-aware routing. Pydantic v2 on every boundary; FastMCP for tools; a verifier LLM that *gates* every response.

## v0 scope

Three domains only: **food**, **supplements**, **conditions** (plus allergies, meds, goals). Skincare, mental health, workouts, and labs are explicitly out of v0.

## Architecture

```
CLI  →  Agent loop (executor + verifier)  →  MCP server  →  SQLite + Pydantic repos
                  ↑
                  └─ ProfileBuilder (cached prefix + volatile suffix)
```

Two LLM calls per turn:

1. **Executor** — sees the cached profile and the MCP tool surface. Emits `Suggestion | Question | ActionConfirmation`. Calls multiple tools in parallel when independent.
2. **Verifier** — runs the executor's reply against the profile. Returns a `SafetyVerdict { ok, flags[], reason }` validated against a JSON Schema. **Hard gate** — if `ok = False`, the executor re-runs with the flag pinned.

## Quick start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure .env (defaults to Groq; pick any free provider)
cp .env.example .env
# edit .env → set LLM_PROVIDER and the matching API key

# 3. Seed sample profile + food catalog
python -m health_agent.apps.seed
# or: health-agent seed

# 4a. Web UI — chat + dashboard at http://127.0.0.1:8000
health-agent-web

# 4b. Terminal REPL
health-agent chat

# 4c. Offline test mode (deterministic fake LLM, no provider needed)
health-agent chat --mock
```

## Layout

```
health_agent/
├── core/                 # agent loop + cached prompt builder
│   ├── agent.py          # executor + verifier, parallel tool dispatch
│   └── profile_builder.py
├── domain/               # rule-based analysis (no DB, no LLM)
│   └── analysis.py
├── db/                   # SQLite schema + one repo per domain
│   ├── schema.py
│   └── repos.py
├── external/             # adapters to external APIs
│   └── usda.py           # USDA FoodData Central
├── llm/                  # LLM clients + prompts
│   ├── client.py         # OpenAICompatClient + V2Client + factory
│   ├── mock.py
│   ├── prompts.py        # executor + verifier (rubric-checked)
│   └── types.py
├── mcp/                  # MCP server wiring
│   └── server.py         # FastMCP — read/mutation/analysis tools
├── models/               # Pydantic v2 schemas
│   ├── medical.py · food.py · supplements.py · agent.py
└── apps/                 # entry points
    ├── cli.py            # terminal REPL
    ├── seed.py           # sample profile + 44-item food catalog
    └── web/              # FastAPI UI
        ├── server.py
        └── static/       # index.html · style.css · app.js
```

## Prompt design rubric

Every system prompt in `health_agent/llm/prompts.py` is annotated against a 9-point rubric: explicit reasoning instructions, structured output format, separation of reasoning and tools, multi-turn support, instructional framing (examples), internal self-checks, reasoning-type tagging, error handling / fallbacks, overall clarity.

## Not a doctor

This is a tracker with suggestions, not medical advice. The verifier checks suggestions against your stated profile (conditions, meds, allergies); it does not vouch for medical correctness.
