"""Register a live Claude Code (Claude Agent SDK) session on AgentOS.

This is the "monitor Claude Code itself via AgentOS" path: Agno ships a
ClaudeAgent class that wraps the Claude Agent SDK, so a Claude Code session
becomes a URL-addressable, session-persistent agent on AgentOS -- every run
shows up traced in the dashboard just like a native Agno agent.

Verified against agno==2.7.2 installed locally:
    from agno.agents.claude import ClaudeAgent
    ClaudeAgent(name=None, id=None, description=None, framework="claude-agent-sdk",
                markdown=True, db=None, system_prompt=None, model=None,
                allowed_tools=None, disallowed_tools=None, permission_mode=None,
                max_turns=None, max_budget_usd=None, cwd=None, mcp_servers=None,
                options_kwargs=...)
permission_mode accepts: "default", "acceptEdits", "plan", "bypassPermissions".
Requires the separate `claude-agent-sdk` PyPI package (it wraps Claude Code as
a subprocess) -- see requirements.txt.

Note on agenthog (theagentos.space, the separate SaaS): its autoinstrument()
patches the in-process `anthropic` Python client, but ClaudeAgent runs Claude
Code as a *subprocess* via claude-agent-sdk -- the LLM calls happen outside
this process, so autoinstrument cannot see them. We still init it below so
any in-process Anthropic/httpx calls Agno itself makes are captured, but
Claude Code's own turns will NOT show up on theagentos.space from this file.

Run locally (separate port from app.py so both can run side by side):
    pip install -r requirements.txt
    cp .env.example .env   # then fill in ANTHROPIC_API_KEY
    uvicorn claude_code_agent_service:app --reload --port 7778
"""

import os

import agenthog
from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your "
        "own key, or export ANTHROPIC_API_KEY in your shell before running "
        "this service."
    )

if os.getenv("AGENTOS_API_KEY"):
    agenthog.init(agent_id=os.getenv("AGENTOS_AGENT_ID", "claude-code"))
    agenthog.autoinstrument()
else:
    print(
        "AGENTOS_API_KEY not set -- skipping agenthog instrumentation. "
        "See .env.example."
    )

db = SqliteDb(db_file="agentos.db")

claude_code_agent = ClaudeAgent(
    name="claude-code",
    model="claude-opus-4-8",
    allowed_tools=["Read", "Edit", "Bash", "Grep", "Glob"],
    permission_mode="acceptEdits",
    db=db,
)

agent_os = AgentOS(
    agents=[claude_code_agent],
    name="claude-code-on-agentos",
    description="Claude Code session exposed as a traced AgentOS agent",
    db=db,
    tracing=True,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="claude_code_agent_service:app", port=7778, reload=True)
