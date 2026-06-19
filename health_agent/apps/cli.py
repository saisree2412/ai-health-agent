"""CLI entry point for health-agent.

Commands:
    seed          — seed the DB with the sample profile + food catalog
    chat          — interactive REPL (use --mock to run without V2)
    review-day    — one-shot "review today's intake" turn
    rubric-check  — print the 9-point rubric coverage for both prompts
    show-prompt   — print the rendered executor or verifier prompt
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from health_agent.core.agent import AgentLoop
from health_agent.db.repos import Repos
from health_agent.db.schema import connect, init_db
from health_agent.llm.client import make_client
from health_agent.models import (
    ActionConfirmation,
    AgentReply,
    Question,
    Suggestion,
)


app = typer.Typer(
    help="health-agent — personal health tracker with verifier-gated suggestions.",
    no_args_is_help=True,
)
console = Console()


# ─── shared bootstrap ──────────────────────────────────────────────────────


def _bootstrap(mock: bool) -> AgentLoop:
    load_dotenv()
    if mock:
        os.environ["LLM_MODE"] = "mock"
    db_path = os.getenv("DB_PATH", "./health_agent.db")
    if not Path(db_path).exists():
        console.print(
            f"[yellow]No DB at {db_path} — run `health-agent seed` first.[/]"
        )
        raise typer.Exit(1)

    conn = connect(db_path)
    init_db(conn)
    repos = Repos(conn)
    llm = make_client()
    return AgentLoop(
        repos=repos,
        llm=llm,
        executor_provider=os.getenv("EXECUTOR_PROVIDER"),
        verifier_provider=os.getenv("VERIFIER_PROVIDER"),
    )


# ─── render helpers ────────────────────────────────────────────────────────


def _render(reply: AgentReply | None) -> None:
    if reply is None:
        console.print("[red]No reply (executor or verifier failed).[/]")
        return
    if isinstance(reply, Suggestion):
        console.print(Panel(reply.message, title="suggestion", border_style="cyan"))
        for rec in reply.recommendations:
            console.print(f"  • {rec.text}  [dim]({rec.reasoning_type})[/]")
            console.print(f"    [dim italic]{rec.rationale}[/]")
        for w in reply.warnings:
            console.print(f"  [yellow]⚠ {w}[/]")
    elif isinstance(reply, Question):
        console.print(Panel(reply.question, title="question", border_style="magenta"))
        console.print(f"  [dim]{reply.why_needed}[/]")
    elif isinstance(reply, ActionConfirmation):
        console.print(Panel(reply.what_was_done, title="confirmed", border_style="green"))
        if reply.summary:
            console.print(f"  [dim]{reply.summary}[/]")


# ─── commands ──────────────────────────────────────────────────────────────


@app.command()
def seed(reset: bool = typer.Option(True, help="Delete the DB first for a clean reseed.")) -> None:
    """Seed the DB with the sample profile + 44-item food catalog."""
    from health_agent.apps.seed import seed as _seed

    _seed(reset=reset)


@app.command()
def chat(
    mock: bool = typer.Option(
        False, "--mock", help="Use the deterministic mock LLM (no V2 required)."
    ),
) -> None:
    """Interactive REPL. `exit` or Ctrl-D to quit."""

    async def _run() -> None:
        loop = _bootstrap(mock)
        await loop.start()
        try:
            if mock:
                mode_label = "mock"
            else:
                llm_mode = (os.getenv("LLM_MODE") or "openai").lower()
                if llm_mode == "v2":
                    mode_label = "llm_gatewayV2 @ " + os.getenv("LLM_GATEWAY_URL", "localhost:8100")
                else:
                    provider = os.getenv("LLM_PROVIDER") or "groq"
                    model = os.getenv("LLM_MODEL") or "(provider default)"
                    mode_label = f"{provider} · {model}"
            console.print(
                Panel(
                    f"health-agent ready  ({mode_label})\nType 'exit' to quit.",
                    style="bold",
                )
            )
            while True:
                try:
                    user_in = console.input("[bold]>[/] ").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    break
                if user_in.lower() in {"exit", "quit"}:
                    break
                if not user_in:
                    continue
                trace = await loop.run_turn(user_in)
                _render(trace.final_reply)
        finally:
            await loop.stop()

    asyncio.run(_run())


@app.command(name="review-day")
def review_day(
    mock: bool = typer.Option(False, "--mock"),
) -> None:
    """One-shot 'review today's intake' turn — designed to exercise multi-tool aggregation."""

    async def _run() -> None:
        loop = _bootstrap(mock)
        await loop.start()
        try:
            trace = await loop.run_turn(
                "Review what I've eaten and taken today and tell me how I'm doing against my goals."
            )
            _render(trace.final_reply)
        finally:
            await loop.stop()

    asyncio.run(_run())


@app.command(name="rubric-check")
def rubric_check() -> None:
    """Show which of the user's 9 rubric points each prompt addresses."""
    from health_agent.llm.prompts import RUBRIC_COVERAGE

    for who, mapping in RUBRIC_COVERAGE.items():
        console.print(Panel(who.upper(), border_style="cyan"))
        for point, where in mapping.items():
            console.print(f"  [bold]{point}[/]  {where}")
        console.print()


@app.command(name="show-prompt")
def show_prompt(
    which: str = typer.Argument(..., help="One of: executor, verifier."),
) -> None:
    """Print the rendered system prompt (with JSON schema spliced in)."""
    from health_agent.llm.prompts import executor_system_prompt, verifier_system_prompt

    if which == "executor":
        console.print(executor_system_prompt())
    elif which == "verifier":
        console.print(verifier_system_prompt())
    else:
        console.print(f"[red]Unknown prompt: {which}. Use 'executor' or 'verifier'.[/]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
