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
about a country and it answers with real census/demographic figures.

```bash
python census_agent.py
# Enter a country name: south korea
```

It resolves the country name fully offline via `pycountry`'s bundled
ISO-3166 database (handles fuzzy input like "uk" or "south korea"), then
fetches population, growth rate, urban share, life expectancy, density, and
surface area from the [World Bank's public API](https://api.worldbank.org)
(no key required), and has Claude turn the figures into a short summary.

The country-resolution logic and the API-response parsing were verified with
mocked HTTP responses in this sandbox (its network policy blocks arbitrary
outbound APIs, so the live World Bank call itself couldn't be exercised
end-to-end here) — test it against the real API on your machine.

## Multi-agent stock analysis (`stock_service.py`)

A three-tier multi-agent system that turns a **free-text question** about a stock
("Should I invest in Apple for the long term?") into an **investment-research
report** — a Favorable / Neutral / Unfavorable rating with confidence, key reasons,
key risks, "what would change this view", and a prominent not-financial-advice
disclaimer. It covers US and Indian (NSE `.NS` / BSE `.BO`) equities.

```
free-text question
  → intake agent (claude-sonnet-5)      extract company + risk/horizon
  → ticker resolution (yfinance search) 1 match, or "did you mean…" back to the UI
  → Tier 1 tools (pure Python)          yfinance prices + pandas indicators; yfinance news
  → Technical + Sentiment analysts      claude-sonnet-5, run in parallel, independently
  → Portfolio Manager (claude-opus-4-8) synthesizes the final report
```

The two analysts never see each other's output (orchestration is deterministic code,
not an autonomous team), technical indicators are computed in pandas so the LLM only
*interprets* them, and if a ticker has no news the Sentiment Analyst is skipped and the
manager is told so (no hallucinated sentiment). Every agent run is traced via AgentOS.

**Design note:** by design this is a *technicals + news-sentiment* view only — it does
**not** analyze fundamentals (earnings, valuation, debt). The report says so explicitly.

### Model provider (Groq / Google / NVIDIA free tiers, or Anthropic)

Set **one** provider key in `.env`. Priority when several are set:
**Groq > Google > NVIDIA > Anthropic**.

- `GROQ_API_KEY` — **Groq**, **free** tier
  ([console.groq.com](https://console.groq.com), key starts `gsk_`). Extremely
  fast with generous free limits — the best fit for this four-call pipeline.
  Defaults: `llama-3.1-8b-instant` (analysts) / `llama-3.3-70b-versatile`
  (manager). Needs the `groq` package.
- `GOOGLE_API_KEY` — Google **Gemini**, **free** tier
  ([aistudio.google.com](https://aistudio.google.com), key starts `AIza`).
  Defaults: `gemini-2.0-flash` (analysts) / `gemini-2.5-flash` (manager). Needs
  `google-genai`. Note: some accounts/regions get `limit: 0` free quota (429
  RESOURCE_EXHAUSTED) — if so, use Groq.
- `NVIDIA_API_KEY` — NVIDIA's **free** OpenAI-compatible endpoint
  ([build.nvidia.com](https://build.nvidia.com), key starts `nvapi-`). Default
  `meta/llama-3.3-70b-instruct` for both tiers. Needs `openai`. (Free tier can
  be slow/rate-limited under bursts.)
- `ANTHROPIC_API_KEY` — Claude (`claude-sonnet-5` / `claude-opus-4-8`). Requires
  prepaid credit on the Anthropic account.

Override model IDs for the chosen provider with `ANALYST_MODEL` / `MANAGER_MODEL`.

### Run

```bash
pip install -r requirements.txt
cp .env.example .env                       # set ANTHROPIC_API_KEY or NVIDIA_API_KEY
(cd frontend && npm install && npm run build)   # first time / after UI changes
uvicorn stock_service:app --port 7779
# open http://localhost:7779  (the React SPA)
# connect https://os.agno.com to http://localhost:7779 for live traces
```

**Windows one-click:** instead of the commands above, just double-click **`run.bat`**
in the project folder. It creates the virtualenv, installs dependencies, prompts you
for your Anthropic API key (opening `.env` in Notepad), starts the server, and opens
your browser at http://localhost:7779. Keep the window open while you use the app;
press Ctrl+C to stop. (It still needs Python 3.11+ installed with "Add Python to PATH".)

The React/Vite SPA (`frontend/`) is served as static files by the same FastAPI app —
one process, one port. The built bundle in `frontend/dist` is committed so the repo
runs without Node; rebuild it after any UI change. For frontend hot-reload during
development, run `uvicorn stock_service:app --port 7779` and `cd frontend && npm run dev`
side by side (the dev server proxies `/api` to the backend).

### Tests

```bash
python -m unittest discover -s tests -v
```

24 tests covering indicator math and JSON-safety, ticker-search ranking, news parsing
(both Yahoo payload shapes), and every `POST /api/analyze` branch (with agents and
yfinance mocked), plus that `/` serves the SPA. As with `census_agent.py`, the **live**
Yahoo Finance and Anthropic calls can't run in this sandbox (network policy) — run one
real query on a machine with open network + an API key to smoke-test end to end.
