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

3. **Optional** — also send traces to [theagentos.space](https://www.theagentos.space)
   via the `agenthog` SDK. This is a *separate, unrelated* third-party SaaS
   (same "AgentOS" name as Agno's product, different company) — get a key
   from them and set `AGENTOS_API_KEY` / `AGENTOS_AGENT_ID` in `.env`. Leave
   it blank to skip this entirely; both services detect the missing key and
   run fine without it (nothing is sent to theagentos.space in that case).

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

## Census data agent (`census_agent.py`)

A separate, standalone CLI agent — not wired into AgentOS or agenthog. Ask it
about a country and it retrieves real census figures, prints them, then has
**`meta/llama-3.1-8b-instruct`** explain them in plain language.

```bash
python census_agent.py
# Enter a country name (blank to quit): south korea

python census_agent.py india     # or pass the country as an argument
```

What it retrieves, and from where:

| Figure                 | Source                                                                 |
| ---------------------- | ---------------------------------------------------------------------- |
| GDP (current US$)      | [World Bank public API](https://api.worldbank.org) — no key needed     |
| Total population       | World Bank public API                                                  |
| Population density     | World Bank public API                                                  |
| Religions followed     | CIA World Factbook, via the [factbook.json](https://github.com/factbook/factbook.json) mirror |

The country name is resolved fully offline via `pycountry`'s bundled ISO-3166
database (handles fuzzy input like "uk" or "south korea"). The Factbook lookup
uses `data/factbook_index.json`, a pre-generated ISO-3166 → Factbook-file map
(regenerate with `python scripts/build_factbook_index.py` if the mirror ever
reorganizes).

**AgentHog tracing (optional):** set `AGENTOS_API_KEY` and
`AGENTOS_WORKSPACE_ID` in `.env` (easiest: run `agenthog init`, which prompts
for both and writes a gitignored `.env`) and every run is traced to
[theagentos.space](https://www.theagentos.space) — one `task_run` per country
lookup, with `resolve_country`, `fetch_world_bank_indicator`,
`fetch_factbook_religions` tool steps and the Llama call nested inside it.
Check traces at [app.theagentos.space/traces](https://app.theagentos.space/traces).
Leave the vars unset and the agent runs exactly as before, sending nothing.

The explanation step calls `meta/llama-3.1-8b-instruct` through NVIDIA's
OpenAI-compatible API — set `NVIDIA_API_KEY` in `.env` (free keys at
[build.nvidia.com](https://build.nvidia.com)). To serve the model yourself
(local NIM, vLLM, …), point `LLM_BASE_URL` at your endpoint instead. If no key
is set or the model call fails, the retrieved data still prints — only the
explanation paragraph is skipped.

Verification status from this sandbox: the Factbook religion lookup and
country resolution were exercised live end-to-end; the World Bank calls and
the NVIDIA endpoint are blocked by the sandbox's network policy, so those
paths were verified with mocked HTTP responses — test them against the real
APIs on your machine.
