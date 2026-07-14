# Claude + AgentOS trace monitoring

Two runnable services that expose Claude-backed agents through
[AgentOS](https://www.agno.com/agentos) (by [Agno](https://github.com/agno-agi/agno))
so every run shows up live in AgentOS's trace/session dashboard.

- **`app.py`** — a plain Agno `Agent` running on the Claude model (`claude-opus-4-8`
  via the Anthropic API). The straightforward path: one process, one agent, full
  tracing.
- **`claude_code_agent_service.py`** — wraps a real **Claude Code** session (via the
  `claude-agent-sdk` package) as an AgentOS agent, using Agno's `ClaudeAgent`
  adapter. This is "Claude Code itself, monitored through AgentOS."

Both were verified end-to-end against `agno==2.7.2` in a clean virtualenv
(imports resolve, `AgentOS(...).get_app()` builds a working FastAPI app, tracing
initializes against the SQLite db) before being committed.

## How it fits together

AgentOS is a FastAPI app you run yourself — nothing is sent to Agno. The
dashboard at [os.agno.com](https://os.agno.com) is just a browser UI that talks
directly to *your* running instance and renders whatever it finds there
(sessions, traces, memory).

```
your Claude API key -> app.py / claude_code_agent_service.py (AgentOS, self-hosted)
                                        |
                          SQLite db (sessions + traces)
                                        |
                     os.agno.com dashboard <- connects to http://localhost:PORT
```

## Setup

1. Create a virtualenv and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Add your own Anthropic API key (get one at
   [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys):

   ```bash
   cp .env.example .env
   # edit .env and set ANTHROPIC_API_KEY=sk-ant-...
   ```

   `.env` is git-ignored — never commit a real key.

## Run

**Plain Claude agent** (port 7777):

```bash
uvicorn app:app --reload --port 7777
```

**Claude Code as an AgentOS agent** (port 7778 — needs `claude-agent-sdk`, already
in `requirements.txt`):

```bash
uvicorn claude_code_agent_service:app --reload --port 7778
```

You can run either one alone, or both at once on their separate ports.

## View traces

1. Start one of the services above.
2. Open [https://os.agno.com](https://os.agno.com) in your browser.
3. Add a new AgentOS connection pointing at `http://localhost:7777` (or `:7778`).
4. Chat with the agent, or call it over HTTP — every run, tool call, and token
   count streams into the dashboard's trace view in real time.

## Notes

- Session/trace data is stored locally in `agentos.db` (SQLite, git-ignored).
  Swap `SqliteDb` for `agno.db.postgres.PostgresDb` in either file for a
  production deployment.
- `claude_code_agent_service.py`'s `ClaudeAgent` runs Claude Code as a
  subprocess via the `claude-agent-sdk` package — `allowed_tools` and
  `permission_mode` scope what it's allowed to do. Tighten these before
  exposing the endpoint beyond local use.
