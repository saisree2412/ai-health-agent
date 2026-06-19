# health-agent — demo script

**Duration:** ~10 minutes  ·  **Audience:** technical (Session-5 / AI cohort)

---

## 0. Pre-flight (do BEFORE the call starts)

```bash
cd ~/Desktop/health-agent

# 1. Make sure DB is freshly seeded with your real profile
health-agent seed

# 2. Start the web UI in one terminal — leave it running
health-agent-web
# → http://127.0.0.1:8000 should load with your sidebar populated

# 3. Have a SECOND terminal open at the project root for the CLI segment.
```

**Tabs to open in your browser, in this order:**
1. http://127.0.0.1:8000 (the live UI)
2. `health_agent/llm/prompts.py` (in your editor or GitHub)
3. `health_agent/mcp/server.py`
4. The terminal where the web server is running (to show provider banner / logs)

**Sanity:** smoke test should be green:
```bash
python -m pytest tests/test_smoke.py -v
```

---

## 1. Hook + context (60s)

> *Say:*
> "Most LLM demos are 'wrap a prompt around GPT and call it an agent.' I wanted to build something that actually exercises every primitive Session 5 talked about — native tool-use, prompt caching, reasoning knobs, structured output, capability-aware routing — on a problem that genuinely needs them.
>
> So I built **health-agent**: a personal health tracker that logs what you eat, what supplements you take, what conditions you live with, and then gives suggestions *that are double-checked against your profile before you ever see them.*
>
> The interesting bit isn't the chat. It's that every reply passes through a second LLM call — a **verifier** — that validates the suggestion against your allergies, conditions, and goals using a JSON-schema-enforced verdict. If it conflicts, the suggestion never reaches you."

---

## 2. Architecture in 90 seconds (do NOT skip)

> *Show:* a slide or just talk it through. Five layers, named.

```
CLI / Web UI
     ↓
Agent loop  (executor + verifier, parallel tool dispatch)
     ↓
MCP server  (~18 tools)
     ↓
SQLite + Pydantic repos   ←  ProfileBuilder reads here
                              for the cached prompt prefix
```

> *Say:*
> "Five layers. Persistence is SQLite with Pydantic on every column. The MCP server exposes ~18 tools — read, mutation, analysis, plus a USDA FoodData Central adapter for unknown foods. The agent loop runs an **executor LLM** with those tools advertised, dispatches parallel tool calls when independent, then runs a **verifier LLM** against the candidate reply.
>
> Pydantic is the spine. The same Macros model defines the JSON schema the LLM sees, validates the tool's input on receive, and types the return value. One source of truth across about 18 tools."

---

## 3. UI tour (90s)

> *Switch to:* the browser tab at `http://127.0.0.1:8000`

Point at each section:

- **Top banner** — "health-agent · personal health tracker"
- **Profile sidebar**:
  - "This is my actual profile: 28F, irregular periods + acne, milk allergy, body recomp + skin goals, Vit D3 1000 IU."
  - *Hover one chip* — "Notice the hover tooltips. Those are the notes the LLM sees when it builds the cached system prompt prefix."
- **Today · macros** — "Six bars: calories, protein, fiber, sodium, added sugar, saturated fat. Limit-style targets go red when exceeded."
- **Today · micros** — "Ten women's-health micros — iron, calcium, magnesium, zinc, Vit D, omega-3, folate, B12, Vit C, potassium. RDAs for adult women anchor each bar. Hover to see why each matters for *me specifically.*"
- **Recent meals** — "Append-only log; X button calls `delete_meal` through the agent's MCP layer."

---

## 4. Live agent loop (3–4 min) — the centerpiece

### 4a. Catalog hit (fast path)

> *Type in chat:* `had a bowl of mixed green salad for lunch`

> *While it runs:*
> "Behind the scenes: ProfileBuilder rendered the cached prefix once. The executor saw 18 tools available. It emitted a `tool_calls` array with `log_meal`. Parallel dispatch via TaskGroup. The catalog had a match, macros were resolved automatically, the log went into SQLite, and the executor produced a `Suggestion` JSON validated against the AgentReply discriminated union. Then the verifier ran — saw no condition conflicts, returned `ok: true` with no flags. Total: 2 LLM calls."

> *Point at sidebar:* "Meal logged. Macro bars ticked up. The deletion button on the right is wired to the same MCP tool the agent would use."

### 4b. Verifier catches an allergen (the money shot)

> *Type:* `had paneer tikka for dinner`

> *Wait for response. Expect:* the agent will note the dairy allergen and either ask you to confirm or suggest swaps.

> *Say:*
> "Paneer is dairy. My profile has 'milk' as a moderate allergy with a note that it can worsen menstrual irregularity. The verifier saw the candidate reply, ran its rule chain — allergen check, condition rules, scope check — and flagged it. The flag came back through the agent loop, and the executor either retried with the flag pinned or surfaced the warning. Notice the amber warning chip on the reply."

### 4c. Unknown food → USDA lookup

> *Type:* `had ragi malt and 15 baby carrots for breakfast`

> *Say while it runs:*
> "Now watch the fallback chain. Catalog misses 'ragi malt' and 'baby carrots' as our exact terms. The agent calls `lookup_food_usda`, gets per-100g data, then — and this is critical — scales the USDA values to a *natural serving unit* before persisting. A mug of ragi malt is 30g of dry flour, not 100g; a baby carrot is 10g, not 100g. The prompt has explicit math walkthroughs for this. Without it, the agent overshoots by 10x — which it *did* in early testing."

> *When the reply lands:* "Check the micros section — iron went up from the ragi, beta-carotene from the carrots. Sodium barely moved. Those numbers are USDA-sourced, not LLM-imagined."

### 4d. Multi-tool reasoning

> *Type:* `give me a quick review of today and flag anything I should worry about`

> *Say:*
> "This turn fans out — `get_today_macros`, `get_recent_meals`, `check_food_against_profile` for each meal, `check_supplement_interactions`. Multiple tools in parallel in one round. The executor reasons over the aggregate and emits a Suggestion with recommendations tagged by `reasoning_type` — `arithmetic`, `logic`, `lookup`, `inference`, `recall`. That's straight off the 9-point rubric — every recommendation is auditable."

---

## 5. Under the hood (2–3 min)

### 5a. Show the 9-point rubric coverage

> *Switch to the second terminal:*
```bash
health-agent rubric-check
```

> *Say:*
> "Every system prompt in this project gets graded against the 9-point rubric from Session 5 — explicit reasoning, structured output, tool/reasoning separation, multi-turn support, in-prompt examples, internal self-checks, reasoning-type tagging, error handling, overall clarity. The CLI prints which section of each prompt covers which point. This is the executor's score; below that is the verifier's. Both green on all 9."

### 5b. Show a prompt

> *Type:*
```bash
health-agent show-prompt verifier
```

> *Scroll briefly:*
> "Notice this isn't just an instruction blob. There's an explicit 5-step process the verifier walks (allergen, condition rules, goal consistency, scope check, structure check), worked examples for blocked and clean verdicts, and the SafetyVerdict JSON Schema embedded directly. The schema is also enforced on the wire via `response_format=json_schema` on providers that support it — Groq, OpenAI, Gemini. For HF/Mistral/Cerebras we downgrade to `json_object` or drop the field, since not every provider accepts the same fields."

### 5c. Show the MCP tool surface

> *Open* `health_agent/mcp/server.py` *or run:*
```bash
grep -c "@mcp.tool" health_agent/mcp/server.py
```

> *Say:*
> "Eighteen MCP tools. Read tools, mutation tools, analysis tools, plus the USDA adapter. Every tool's input schema and return type are the same Pydantic models — the LLM sees the schema, the dispatcher validates the call, and the agent loop gets a typed return. That's the 'Pydantic on every boundary' rule applied across the entire tool surface."

### 5d. Show the smoke test

> *Type:*
```bash
python -m pytest tests/test_smoke.py -v
```

> *Say:*
> "Smoke test runs end-to-end in mock mode — no provider needed. Asserts: three parallel tool calls fire on the first executor round, the food rule engine flags pepperoni pizza for sodium-vs-hypertension, the verifier returns ok=true with the warning attached. Covers the whole loop in under a second. It also caught two real bugs during development — a SQLite WAL deadlock under parallel fan-out, and the MCP SDK silently stripping custom env vars from the subprocess."

---

## 6. Highlights — Session-5 features that actually fire (60s)

> *Say:*

| Feature | Where it lives in this project |
|---|---|
| Native tool-use (no JSON parsing hacks) | `OpenAICompatClient` translates per-provider |
| Prompt caching | `ProfileBuilder.cached_prefix()` + `cache_system=True`; profile is bulky and stable |
| Reasoning knob | `reasoning="medium"` on executor's first round; mapped to `reasoning_effort` for providers that support it |
| Structured output | `response_format=json_schema(SafetyVerdict)` on the verifier — hard gate, not advisory |
| Capability-aware routing | Three tiers — providers that get json_schema, json_object, or no response_format at all; retry with backoff on 429/503 |

> "And on top of those: a mock client that fully replays the agent loop offline, retry-with-backoff on rate limits, and a 'lighter verifier model' env var so you split the executor's full-power model from a cheaper verifier — `LLM_VERIFIER_MODEL=gemini-2.5-flash-lite`."

---

## 7. Likely questions (prep, don't read aloud)

**Q: How is this not just "ChatGPT with a system prompt"?**
A: Three things. (1) The verifier *gates* every reply — it's a hard validation step, not advisory. (2) The tool surface is local and typed — Pydantic everywhere — so the LLM can't drift on data shapes. (3) The profile + rule engine make the recommendations *personal* and *auditable*; you can quote the exact profile fact that triggered a flag.

**Q: What if the verifier itself is wrong?**
A: It's bounded by my profile, not medical correctness. It says "this conflicts with your stated allergy" — that's a tractable claim. It does NOT say "this is medically safe." The README is explicit about this.

**Q: Why MCP and not just Python functions?**
A: Two reasons. (1) Session-5 pattern — the same MCP server can serve other agents (e.g., a notebook or another LLM client). (2) It forces the typed boundary — every tool's JSON Schema is what the LLM sees, no leakage from internal Python representations.

**Q: How do you handle providers that ratе-limit or 400 on weird fields?**
A: Three layers. (1) Capability-aware request shaping — provider sets that support `reasoning_effort` vs. `json_schema` vs. `json_object` vs. nothing. (2) Retry-with-backoff on 429/502/503/504 honoring `Retry-After` headers. (3) Lighter verifier model option to split quota between executor and verifier.

**Q: Why 18 macros / micros and not more?**
A: 11 of them are the ones that materially shape recommendations for a 28F with irregular periods and acne — iron, zinc, magnesium, B12, omega-3, etc. More fields wouldn't change the verifier's behavior; fewer would miss the women's-health story.

**Q: Couldn't an LLM do all the rule-checking?**
A: Yes — but unreliably and unauditably. The pure-Python rule engine in `domain/analysis.py` is deterministic. The verifier LLM uses these rules to ground its reasoning; it doesn't replace them.

**Q: What's next?**
A: Lab/blood-profile support (model + tools), workouts, weekly trend reports, multi-user. Architecturally it's pluggable — the v0 scope was deliberately narrow.

---

## 8. Closing line (15s)

> *Say:*
> "If I had to summarize what this project showed me: the agent loop isn't the hard part. The hard part is making the *boundaries* trustworthy — between user and LLM, between LLM and tools, between tool result and persisted state. Pydantic, MCP, and the verifier-as-hard-gate are the three things that buy you that trust. Thanks — happy to take questions."

---

## Fallback paths if something breaks live

| If… | Do this |
|---|---|
| Provider rate-limits mid-demo | Banner shows current provider; flip `LLM_PROVIDER` in `.env`, restart server (15s) |
| Server won't start | `python -m health_agent.apps.seed` then `health-agent-web` again |
| Agent gives malformed JSON | Verifier-retry will kick in automatically; just note "you can see the retry in the terminal logs" |
| USDA lookup times out | Tell the audience "USDA throttles DEMO_KEY hard — in real use you'd set USDA_API_KEY". Continue with catalog foods |
| You forget what to say next | Look at the sidebar — there's always something to point at |
