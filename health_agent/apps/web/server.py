"""FastAPI web UI for health-agent.

Architecture:
    - One AgentLoop spawned at process startup (FastAPI lifespan).
    - Shared SQLite connection (WAL mode, check_same_thread=False) reused
      across requests; FastAPI handles request concurrency.
    - REST API exposes: chat, profile snapshot, today's macros, recent meals.
    - Static frontend (HTML/CSS/JS) served from ./static/.

Run:
    health-agent-web                                    # console script
    uvicorn health_agent.apps.web.server:app --reload   # for dev
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from health_agent.core.agent import AgentLoop
from health_agent.db.repos import Repos
from health_agent.db.schema import connect, init_db
from health_agent.llm.client import make_client


STATIC_DIR = Path(__file__).parent / "static"


# ─────────────────────────── lifespan ──────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_dotenv()
    db_path = os.getenv("DB_PATH", "./health_agent.db")
    if not Path(db_path).exists():
        raise RuntimeError(
            f"No DB at {db_path}. Run `python -m health_agent.apps.seed` first."
        )

    conn = connect(db_path)
    init_db(conn)
    repos = Repos(conn)
    llm = make_client()
    loop = AgentLoop(
        repos=repos,
        llm=llm,
        executor_provider=os.getenv("EXECUTOR_PROVIDER"),
        verifier_provider=os.getenv("VERIFIER_PROVIDER"),
    )
    await loop.start()

    app.state.repos = repos
    app.state.loop = loop
    # Serialize chat calls — AgentLoop holds an MCP subprocess that isn't
    # meant to handle parallel run_turn from one client.
    app.state.chat_lock = asyncio.Lock()

    try:
        yield
    finally:
        await loop.stop()


app = FastAPI(title="health-agent", lifespan=lifespan)


# ─────────────────────────── request models ────────────────────────────────


class ChatRequest(BaseModel):
    message: str


# ─────────────────────────── API ───────────────────────────────────────────


@app.get("/api/profile")
async def get_profile() -> dict:
    r: Repos = app.state.repos
    p = r.profile.get()
    return {
        "profile": p.model_dump(mode="json") if p else None,
        "conditions": [c.model_dump(mode="json") for c in r.conditions.list_active()],
        "medications": [m.model_dump(mode="json") for m in r.medications.list_active()],
        "allergies": [a.model_dump(mode="json") for a in r.allergies.list_all()],
        "goals": [g.model_dump(mode="json") for g in r.goals.list_active()],
        "supplements": [s.model_dump(mode="json") for s in r.supplements.list_active()],
    }


@app.get("/api/today")
async def get_today() -> dict:
    r: Repos = app.state.repos
    today = date.today()
    meals = r.meal_log.for_date(today)
    sups = r.supplement_log.for_date(today)
    totals = r.meal_log.sum_macros_for_date(today)
    return {
        "date": today.isoformat(),
        "meals": [m.model_dump(mode="json") for m in meals],
        "supplements": [s.model_dump(mode="json") for s in sups],
        "totals": totals.model_dump(mode="json"),
    }


@app.get("/api/meals")
async def get_meals(limit: int = 10) -> list[dict]:
    r: Repos = app.state.repos
    return [m.model_dump(mode="json") for m in r.meal_log.recent(limit)]


@app.delete("/api/meals/{meal_id}")
async def delete_meal(meal_id: int) -> dict:
    r: Repos = app.state.repos
    deleted = r.meal_log.delete(meal_id)
    if not deleted:
        raise HTTPException(404, f"meal {meal_id} not found")
    return {"deleted": True, "meal_id": meal_id}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    loop: AgentLoop = app.state.loop
    async with app.state.chat_lock:
        try:
            trace = await loop.run_turn(req.message)
        except Exception as e:
            raise HTTPException(500, f"agent error: {type(e).__name__}: {e}") from None
    return {
        "reply": trace.final_reply.model_dump(mode="json") if trace.final_reply else None,
        "events_tail": [e.model_dump(mode="json") for e in trace.events[-10:]],
        "session_id": trace.session_id,
    }


# ─────────────────────────── static ────────────────────────────────────────


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ─────────────────────────── entry point ───────────────────────────────────


def run() -> None:
    """Console script entry — `health-agent-web`."""
    import uvicorn

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    uvicorn.run(
        "health_agent.apps.web.server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    run()
