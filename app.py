"""AgentOS service exposing a Claude-backed Agno agent with tracing enabled.

Run locally:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in ANTHROPIC_API_KEY
    uvicorn app:app --reload --port 7777

Then open https://os.agno.com in your browser and connect it to
http://localhost:7777 (or wherever you deploy this). The dashboard talks
directly to this running instance from your browser -- no data goes to Agno.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your "
        "own key, or export ANTHROPIC_API_KEY in your shell before running "
        "this service."
    )

# Sessions, memory, and traces are persisted here -- swap for PostgresDb in
# production (see agno.db.postgres.PostgresDb).
db = SqliteDb(db_file="agentos.db")

claude_agent = Agent(
    name="claude-assistant",
    model=Claude(id="claude-opus-4-8"),
    db=db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

agent_os = AgentOS(
    agents=[claude_agent],
    name="agentos-trace-monitoring",
    description="AgentOS instance exposing a Claude-backed agent with tracing enabled",
    db=db,
    tracing=True,
)

# uvicorn app:app picks this up.
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="app:app", port=7777, reload=True)
