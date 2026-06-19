"""End-to-end smoke test in --mock mode.

Verifies the full path:
    user message
      → executor (mock) emits 3 parallel tool_calls
      → MCP subprocess dispatches them
      → executor emits a Suggestion JSON
      → verifier (mock) emits a SafetyVerdict (ok=true with sodium warning)
      → agent attaches the warning to the Suggestion and returns it

Run with:
    pytest -xvs tests/test_smoke.py
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from health_agent.apps.seed import seed
from health_agent.core.agent import AgentLoop
from health_agent.db.repos import Repos
from health_agent.db.schema import connect, init_db
from health_agent.llm.mock import MockClient
from health_agent.models import Suggestion


@pytest.mark.asyncio
async def test_pizza_scenario_end_to_end() -> None:
    # NOTE: we use /tmp explicitly because some sandboxed CI filesystems
    # (overlay / 9p mounts) don't support the unix locking SQLite needs.
    # On a normal machine, tempfile.TemporaryDirectory() would be fine.
    tmp_root = Path(tempfile.gettempdir())
    if not str(tmp_root).startswith("/tmp"):
        tmp_root = Path("/tmp")
    tmp_dir = tmp_root / f"health-agent-test-{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        db_path = tmp_dir / "h.db"
        os.environ["DB_PATH"] = str(db_path)
        os.environ["LLM_MODE"] = "mock"

        # 1. Seed
        seed(db_path=str(db_path))
        assert db_path.exists()

        # 2. Wire up loop
        conn = connect(str(db_path))
        init_db(conn)
        repos = Repos(conn)
        llm = MockClient()
        loop = AgentLoop(repos=repos, llm=llm)
        await loop.start()
        try:
            trace = await loop.run_turn("had 2 slices of pepperoni pizza for lunch")
        finally:
            await loop.stop()

        # 3. Three parallel tool_calls in the first executor round
        tool_call_events = [e for e in trace.events if e.kind == "tool_call"]
        assert len(tool_call_events) == 3, (
            f"expected 3 parallel tool calls, got {len(tool_call_events)}: "
            f"{[e.payload['name'] for e in tool_call_events]}"
        )
        tool_names = {e.payload["name"] for e in tool_call_events}
        assert tool_names == {
            "log_meal",
            "check_food_against_profile",
            "get_today_macros",
        }, f"unexpected tools: {tool_names}"

        # 4. Tool results all returned
        tool_result_events = [e for e in trace.events if e.kind == "tool_result"]
        assert len(tool_result_events) == 3

        # 5. check_food_against_profile returned a non-empty flag list
        food_check = next(
            e for e in tool_result_events if e.payload["name"] == "check_food_against_profile"
        )
        flags = food_check.payload["result"]
        assert isinstance(flags, list) and len(flags) > 0, (
            "expected sodium/condition flags for pepperoni pizza; got " f"{flags}"
        )

        # 6. Final reply is a Suggestion with the verifier's warning attached
        assert isinstance(trace.final_reply, Suggestion), (
            f"expected Suggestion, got {type(trace.final_reply).__name__}: "
            f"{trace.final_reply!r}"
        )
        assert any(
            "sodium" in w.lower() for w in trace.final_reply.warnings
        ), f"expected a sodium warning in {trace.final_reply.warnings}"

        # 7. Exactly one verdict event recorded
        verdicts = [e for e in trace.events if e.kind == "verdict"]
        assert len(verdicts) == 1
        verdict_payload = verdicts[0].payload
        assert verdict_payload["ok"] is True
    finally:
        # Cleanup the tmp dir
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)
