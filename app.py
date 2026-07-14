"""AgentOS service exposing a Claude-backed Agno agent with tracing enabled.

Run locally:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in ANTHROPIC_API_KEY (and optionally AGENTOS_API_KEY)
    uvicorn app:app --reload --port 7777

Then open https://os.agno.com in your browser and connect it to
http://localhost:7777 (or wherever you deploy this). The dashboard talks
directly to this running instance from your browser -- no data goes to Agno.

Separately, if AGENTOS_API_KEY is set, every Anthropic API call this agent
makes is also traced to theagentos.space via the `agenthog` SDK (a different,
unrelated "AgentOS" -- a hosted third-party service). This is optional and
independent of the Agno tracing above.
"""

import os

import agenthog
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

# Optional: send traces to theagentos.space (separate from Agno's own
# tracing above). Skipped entirely if no key is configured.
if os.getenv("AGENTOS_API_KEY"):
    agenthog.init(agent_id=os.getenv("AGENTOS_AGENT_ID", "claude-assistant"))
    agenthog.autoinstrument()  # patches the anthropic client Agno's Claude model uses
else:
    print(
        "AGENTOS_API_KEY not set -- skipping agenthog instrumentation "
        "(traces will not be sent to theagentos.space). See .env.example."
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
