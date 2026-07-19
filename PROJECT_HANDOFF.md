# Multi-Agent Stock Analysis — Project Handoff

This document is a complete handoff for the multi-agent stock analysis system. It
is written so another agent (or engineer) can take over with **no additional
context**: it covers the original request, every decision made, the full tech
stack, the file layout, the website design, all styling/theming decisions, and
the current build status. The current status section at the bottom is the first
thing to read when resuming.

---

## 1. What we're building (original request)

A **multi-tier multi-agent system** that takes a user's free-text question about a
stock and returns an **investment-research report** advising whether the stock is
worth considering. The architecture mirrors the user's diagram:

```
[Tier 3: Portfolio Manager]  <-- makes the final call
            ^
   +--------+--------+
   |                 |
[Tier 2:          [Tier 2:
 Technical         Sentiment
 Analyst]          Analyst]
   ^                 ^
[Tier 1:          [Tier 1:
 Stock API]        News Scraper]
```

Lower tiers gather/clean data; middle tier analyzes; top tier decides.

## 2. Decisions locked with the user (do not re-litigate)

| Topic | Decision |
|---|---|
| **Output** | A research **report**, not trade execution. Rating = Favorable / Neutral / Unfavorable, with confidence, key reasons, key risks, "what would change this view", and a prominent **not-financial-advice** disclaimer. |
| **Markets** | US stocks **and** Indian stocks (NSE `.NS` / BSE `.BO` suffixes). Long-term horizon focus. |
| **Analysts** | Exactly **two** — Technical + Sentiment. No fundamental analyst (user chose to stay faithful to the diagram). The report explicitly caveats that it covers technicals + sentiment only, **no fundamentals**. |
| **Analyst independence** | The two analysts **never see each other's output**. Enforced by deterministic code orchestration, not an autonomous agent team. |
| **Data source** | **Free only** — `yfinance` for prices, stats, and per-ticker news. No paid APIs, no literal web scraping. |
| **User input** | **Free text** ("should I buy Reliance?"). An intake agent extracts the company + any stated risk/horizon. Ambiguous company → UI shows a "did you mean…" picker before any analysis runs. Two companies named → ask the user to pick one (no comparison in v1). |
| **Indicators** | Computed **deterministically in Python (pandas)**. The LLM only *interprets* a compact indicator table — it never computes numbers. |
| **Models** | `claude-sonnet-5` for intake + both analysts; `claude-opus-4-8` for the Portfolio Manager (the judgment call). |
| **UI** | Full **React/Vite SPA**: question box → optional disambiguation picker → staged loading → report page (rating card, two analyst verdict cards, interactive 1-year price chart, disclaimer). No live streaming, no headline list, no history browser in v1. |
| **Serving** | `vite build` output served as static files by the **same FastAPI app** — one process, one port (**7779**). |
| **Observability** | Agents registered on **AgentOS** with tracing (SQLite `agentos.db`), viewable at os.agno.com — same pattern as the repo's existing `app.py`. |
| **Comparison** | Single stock only in v1. If two are named, ask the user to choose. |
| **Report voice** | Explicit rating + disclaimer (not bare "buy/hold/sell", not a no-verdict brief). |

## 3. Tech stack & frameworks

### Backend (Python 3.11)
- **Agno** (`agno==2.7.4`) — the agent framework. `Agent` instances with a Pydantic
  `output_schema` for structured output; `arun()` for async execution.
- **AgentOS** (`agno.os.AgentOS`) — wraps the agents in a FastAPI app with tracing
  enabled; the dashboard at os.agno.com connects to the local instance. `get_app()`
  returns the FastAPI app we extend with our own routes.
- **Anthropic** (`anthropic` SDK) — the model provider, via `agno.models.anthropic.Claude`.
  Models: `claude-sonnet-5` (analysts/intake), `claude-opus-4-8` (manager).
- **yfinance** (`yfinance==1.5.1`) — free Yahoo Finance data: `Ticker.history()` for
  1y OHLCV, `Ticker.get_news()` for headlines, `Search()` for ticker resolution.
- **pandas** (`pandas==3.0.3`) — deterministic indicator computation.
- **FastAPI** + **uvicorn** — HTTP server. `python-multipart` is a required runtime
  dep (AgentOS routes use form parsing).
- **Pydantic v2** — schemas shared between the agents' structured output and the HTTP API.
- **python-dotenv** — loads `ANTHROPIC_API_KEY` (and optional `AGENTOS_API_KEY`) from `.env`.
- **opentelemetry-api/sdk + openinference-instrumentation-agno** — required for AgentOS
  tracing to actually emit spans (already in `requirements.txt`).
- Optional: **agenthog** — sends traces to theagentos.space (a separate third-party
  SaaS); only activates if `AGENTOS_API_KEY` is set. Skipped otherwise.

### Frontend (Node 22)
- **React 18** + **Vite 5** (`@vitejs/plugin-react`). Plain JSX, no TypeScript.
- **No chart library** — the price chart is a hand-rolled **SVG** component
  (`PriceChart.jsx`) with a crosshair + tooltip hover layer. This keeps the bundle
  self-contained and gives full control over the one-axis design (see §6).
- Dev server proxies `/api` → `http://localhost:7779` (see `vite.config.js`).
- Production build (`npm run build`) → `frontend/dist/`, served by FastAPI.

## 4. File layout

```
Claude-Attempt-1/
├── stock_service.py            # ENTRYPOINT. AgentOS/FastAPI app on :7779.
│                               #   Orchestrates the pipeline, exposes POST /api/analyze,
│                               #   serves the built SPA.
├── stock_analysis/
│   ├── __init__.py
│   ├── schemas.py              # All Pydantic models: IntakeResult, AnalystVerdict,
│   │                           #   FinalReport, TickerCandidate, Profile, ChartSeries,
│   │                           #   AnalyzeRequest, AnalyzeComplete/Ambiguous/NotFound.
│   ├── agents.py               # The four Agno agents (intake, technical, sentiment,
│   │                           #   manager) with system prompts + output_schema + models.
│   └── tools/
│       ├── __init__.py
│       ├── market_data.py      # Tier 1: yfinance price fetch, pandas indicators
│       │                       #   (SMA20/50/200, RSI14, MACD, 52w range, volatility,
│       │                       #   volume trend, MA cross), chart series, ticker search.
│       └── news.py             # Tier 1: yfinance news fetch + cleaning/dedup.
├── frontend/
│   ├── package.json            # react, react-dom, vite, @vitejs/plugin-react
│   ├── vite.config.js          # build → dist/, dev proxy /api → :7779
│   ├── index.html
│   ├── dist/                   # BUILT SPA (committed so the repo runs without Node)
│   └── src/
│       ├── main.jsx            # React entry
│       ├── App.jsx             # State machine: input | loading | ambiguous | report | error
│       ├── PriceChart.jsx      # SVG price+volume chart with hover crosshair/tooltip
│       └── styles.css          # All styling + light/dark theming (see §7)
├── requirements.txt            # Backend deps (yfinance, pandas added to existing set)
├── .env.example                # ANTHROPIC_API_KEY (+ optional AGENTOS_API_KEY)
├── README.md                   # Setup/run docs (has a new stock-analysis section)
├── PROJECT_HANDOFF.md          # THIS FILE
│
│   # Pre-existing, unrelated to this feature — leave alone:
├── app.py                      # Existing plain Claude AgentOS agent (port 7777)
├── claude_code_agent_service.py# Existing Claude-Code-as-agent service (port 7778)
└── census_agent.py             # Existing standalone census CLI agent
```

## 5. Data flow / API contract

**`POST /api/analyze`**, body `{ question: str, ticker?: str }`:

1. If `ticker` is present (user picked from the disambiguation list) → skip resolution,
   run intake only for the profile, then run the full pipeline on that ticker.
2. Else run **intake agent** → extract `companies[]`, `risk_tolerance`, `horizon`.
   - No company found → `{status: "not_found", message}`.
   - >1 company → `{status: "ambiguous", candidates, message}` (pick one).
   - 1 company → `yfinance` search for candidates. Unambiguous top match → analyze;
     otherwise → `{status: "ambiguous", candidates}` ("did you mean…").
3. Full pipeline (`_analyze_ticker`):
   - **Tier 1**: `market_data.fetch_market_data(ticker)` (1y history → indicators +
     chart) and `news.fetch_news(ticker)` (run off-thread via `asyncio.to_thread`).
   - **Tier 2**: Technical analyst (indicator summary) and Sentiment analyst
     (headlines) run **in parallel** via `asyncio.gather`. If **no news**, the
     sentiment analyst is **skipped** and the manager is told sentiment was unavailable.
   - **Tier 3**: Portfolio manager synthesizes both verdicts + the investor profile
     into a `FinalReport`.
   - Response: `{status: "complete", company, ticker, currency, profile, technical,
     sentiment, sentiment_unavailable, report, chart, indicator_summary, headline_count}`.

One blocking request (~30–60s); the frontend shows staged loading copy.

## 6. Website design / layout

Single-page app, max-width ~900px, centered. Five visual states in `App.jsx`:

1. **Header** (always visible): title "Multi-Agent Stock Analysis" + one-line tagline
   explaining the two-analyst-plus-manager design.
2. **Ask form** (always visible): text input + "Analyze" button. Placeholder shows an
   example free-text question.
3. **Loading**: centered spinner + a message that advances through five staged strings
   ("Understanding your question…" → … → "Portfolio manager writing the report…"),
   plus a note that it runs four Claude agents and can take up to a minute.
4. **Disambiguation**: a card with the prompt message and a vertical list of candidate
   buttons (`TICKER — Name — Exchange`); clicking one re-submits with that ticker.
5. **Report**:
   - **Header row**: company name + ticker, and a "← New analysis" link.
   - **Verdict card**: a colored rating **badge** (Favorable=green / Neutral=amber /
     Unfavorable=red), confidence %, a one-line summary, a profile note ("Assessed for
     a *moderate* investor over a *long (3y+)* horizon"), and a 3-column grid of
     **Key reasons / Key risks / What would change this view**.
   - **Price chart** (`PriceChart.jsx`): see below.
   - **Analyst row**: two side-by-side cards (Technical, Sentiment). Each shows a signal
     **pill** (bullish/bearish/neutral), confidence, summary, an Evidence list, and a
     Caveats list. If sentiment was unavailable, that card shows an explanatory note.
   - **Indicators `<details>`**: collapsible; shows the exact plain-text indicator table
     the technical analyst read, plus the headline count.
   - **Disclaimer**: an amber-left-bordered block with the not-financial-advice +
     no-fundamentals text.
6. **Footer** (always visible): a muted disclaimer line + note that runs are traced via AgentOS.

### Chart design (important — one-axis rule)
The price chart deliberately **avoids a dual-axis** design. It has two stacked panels
sharing the x-axis:
- **Price panel** (top, ~300px): three line series on one price axis — **Close** (blue,
  2px), **SMA 50** (orange, 1.6px), **SMA 200** (violet, 1.6px). Gridlines + y-axis price
  ticks (nice-number algorithm).
- **Volume panel** (bottom, ~90px): thin vertical volume bars, own implied scale, labeled
  "vol".
- **Hover layer**: a dashed crosshair, colored dot markers on each line, and an absolutely
  positioned tooltip showing the date, each series value + currency, and the volume.
- A **legend** (swatch + label per series) sits above the SVG. x-axis shows first / middle /
  last dates.

## 7. Styling, colors & theming (all decided)

Defined entirely in `frontend/src/styles.css` using CSS custom properties. **Theme-aware**:
defaults to the OS preference via `@media (prefers-color-scheme: dark)`, and also honors an
explicit `:root[data-theme="light"|"dark"]` override (so a future theme toggle can win).

### Chart categorical palette — VALIDATED
The three line-series colors were validated with the `dataviz` skill's
`validate_palette.js` (all six checks PASS in **both** light and dark on their respective
surfaces — lightness band, chroma floor, CVD adjacent-pair separation, normal-vision floor,
contrast). **Do not swap these for un-validated colors.**

| Series | Light hex | Dark hex |
|---|---|---|
| Close (`--close`) | `#2a78d6` (blue) | `#3987e5` |
| SMA 50 (`--sma50`) | `#eb6834` (orange) | `#d95926` |
| SMA 200 (`--sma200`) | `#4a3aa7` (violet) | `#9085e9` |

### UI surface / text tokens
| Token | Light | Dark |
|---|---|---|
| `--surface-0` (page bg) | `#f4f2ee` | `#131312` |
| `--surface-1` (cards/chart) | `#fcfcfb` | `#1a1a19` |
| `--surface-2` (insets) | `#efede8` | `#232320` |
| `--border` | `#dcdad3` | `#34342f` |
| `--text-primary` | `#0b0b0b` | `#ffffff` |
| `--text-secondary` | `#52514e` | `#c3c2b7` |
| `--text-muted` | `#86847d` | `#8f8e84` |

### Status colors (rating badges / signal pills)
| Token | Light | Dark | Used for |
|---|---|---|---|
| `--good` | `#008300` | `#46c246` | Favorable rating, bullish signal |
| `--warn` | `#eda100` | `#e6b33a` | Neutral rating, disclaimer accent |
| `--bad` | `#d33a37` | `#e66767` | Unfavorable rating, bearish signal, errors |

Signal pills use a `color-mix()` tint of the status color for the background with the solid
status color as text. Rating badges are solid status color with white (or black on amber) text.

### Type / shape
System font stack. Card radius `12px` (`--radius`), soft shadow (`--shadow`). Section
headings are uppercase, letter-spaced, `--text-secondary`. Tabular-nums for tickers/prices.
Responsive: analyst row and verdict grid collapse to one column under ~640px; the chart SVG
is `width:100%` with `overflow:visible`.

## 8. How to run

```bash
# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set ANTHROPIC_API_KEY=sk-ant-...

# Frontend (first time / after UI changes)
cd frontend && npm install && npm run build && cd ..

# Serve everything on one port
uvicorn stock_service:app --port 7779
# open http://localhost:7779   (SPA)
# connect https://os.agno.com to http://localhost:7779 for traces
```

Frontend dev with hot reload (two terminals): `uvicorn stock_service:app --port 7779` +
`cd frontend && npm run dev` (proxies /api to the backend).

## 9. Verification done
- Backend imports and the FastAPI app builds (`python -c "import stock_service"`).
- **Committed unit tests** in `tests/` (stdlib `unittest`, no extra dep) —
  run `python -m unittest discover -s tests -v`. 24 tests, all passing:
  - `tests/test_tools.py`: indicator math + chart series are JSON-safe (no NaN/inf),
    RSI in range, cross-state valid, too-short history raises; ticker-search ranking,
    equity-type filtering, dedup, error→[] fallback; news parsing for **both** the new
    nested `content` shape and the old flat shape, dedup, empty-headline rendering.
  - `tests/test_service.py`: every `POST /api/analyze` branch with mocked agents +
    yfinance — complete, no-news (sentiment skipped), two-company ambiguous, one-name
    multi-match ambiguous, no-company/no-match not_found, ticker fast-path skips
    resolution; plus `GET /` serves the SPA HTML (not AgentOS JSON) and `/api/health`.
- Frontend builds cleanly and **reproducibly** (`npm run build` → 32 modules, ~152KB JS;
  identical content-hashed filenames as the committed `frontend/dist`).
- **Live Yahoo Finance / Anthropic calls were NOT exercised** — this sandbox's network
  policy blocks arbitrary outbound APIs (same limitation as `census_agent.py`). Test
  against real yfinance + a real `ANTHROPIC_API_KEY` on a machine with open network.

## 10. Git
- Branch: `claude/multi-agent-stock-analysis-2wdq73`.
- Commit + push the whole feature (backend, frontend source **and** `frontend/dist`).

---

## CURRENT STATUS (read this first when resuming)

**Status: feature complete and verified against mocks. Ready to commit + push.**
Last updated: 2026-07-19.

Done:
- ✅ Full backend: schemas, Tier-1 tools, four agents, orchestration service.
- ✅ Committed unit tests in `tests/` — **24 passing** (`python -m unittest discover -s tests -v`):
  indicators/chart JSON-safety, ticker search ranking, news parsing (both shapes), and
  every `/api/analyze` branch + static serving. See §9.
- ✅ Full frontend written and **builds reproducibly** (`frontend/dist` committed).
- ✅ Chart palette validated (light + dark) via the dataviz skill.
- ✅ FastAPI serves `/api/analyze`, `/api/health`, static `/assets/*`, **and `/` (the SPA)**.
- ✅ **Route-conflict bug FIXED.** The SPA-at-`/` problem was real: AgentOS's own
  management API also claims `GET /`, so `/` returned AgentOS JSON instead of the SPA.
  Fixed in `stock_service.py` by registering our routes on a `base_app = FastAPI()` and
  passing it to `AgentOS(base_app=base_app, on_route_conflict="preserve_base_app")`, then
  calling `agent_os.get_app()` **after** our routes are declared. Verified via TestClient:
  `GET /` → 200 `text/html` with `<div id="root">`; AgentOS's own `/config` still 200.
- ✅ `requirements.txt` updated (`yfinance`, `pandas`, `python-multipart`); `.gitignore`
  now excludes `node_modules/`.

Remaining:
- [ ] Commit + push to `claude/multi-agent-stock-analysis-2wdq73` (in progress).
- [ ] (Optional, needs real network + API key) smoke-test one real query end to end on an
  open-network machine — the only thing this sandbox could not exercise.

Nothing about the design or decisions is outstanding. The implementation is complete;
only the live-network smoke test remains, and it requires an environment this sandbox
cannot provide.
