"""Multi-agent stock analysis service (AgentOS + FastAPI).

Pipeline (see stock_analysis/ for the pieces):

    free-text question
        -> intake agent           (extract company + risk/horizon)
        -> ticker resolution       (yfinance search; may ask the user to disambiguate)
        -> Tier 1 tools            (market data + news, pure Python)
        -> Technical + Sentiment   (two analysts, run in parallel, independently)
        -> Portfolio Manager       (synthesize the final report)

Every agent run is traced through AgentOS (open https://os.agno.com and connect
it to http://localhost:7779). The React SPA in frontend/dist is served at /.

Run locally:
    pip install -r requirements.txt
    cp .env.example .env   # then set ANTHROPIC_API_KEY
    (cd frontend && npm install && npm run build)   # first time / after UI changes
    uvicorn stock_service:app --port 7779
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional, Union

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from stock_analysis.agents import (
    build_intake_agent,
    build_manager_agent,
    build_sentiment_agent,
    build_technical_agent,
)
from stock_analysis.schemas import (
    AnalyzeAmbiguous,
    AnalyzeComplete,
    AnalyzeNotFound,
    AnalyzeRequest,
    AnalystVerdict,
    IntakeResult,
    Profile,
)
from stock_analysis.tools import market_data, news

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your own "
        "key, or export ANTHROPIC_API_KEY in your shell before running this service."
    )

# Optional: also trace to theagentos.space via agenthog (same pattern as app.py).
if os.getenv("AGENTOS_API_KEY"):
    import agenthog

    agenthog.init(agent_id=os.getenv("AGENTOS_AGENT_ID", "stock-analysis"))
    agenthog.autoinstrument()
else:
    print(
        "AGENTOS_API_KEY not set -- skipping agenthog instrumentation "
        "(nothing sent to theagentos.space). See .env.example."
    )

db = SqliteDb(db_file="agentos.db")

intake_agent = build_intake_agent(db)
technical_agent = build_technical_agent(db)
sentiment_agent = build_sentiment_agent(db)
manager_agent = build_manager_agent(db)

# Our own routes (/, /api/*, /assets) live on this base app. AgentOS mounts its
# own management API (which itself claims GET /) on top; on_route_conflict=
# "preserve_base_app" makes our routes win so `/` serves the SPA, not AgentOS's
# JSON. Routes are registered on `base_app` below, before get_app() runs.
base_app = FastAPI(title="stock-analysis")

agent_os = AgentOS(
    name="stock-analysis",
    description="Multi-tier multi-agent stock analysis with AgentOS tracing",
    agents=[intake_agent, technical_agent, sentiment_agent, manager_agent],
    db=db,
    base_app=base_app,
    on_route_conflict="preserve_base_app",
    tracing=True,
)

app: FastAPI = base_app


# --- Pipeline steps ---------------------------------------------------------


async def _run_intake(question: str) -> IntakeResult:
    output = await intake_agent.arun(question)
    result = output.content
    if not isinstance(result, IntakeResult):
        # Defensive: fall back to treating the whole question as one company.
        return IntakeResult(companies=[question])
    return result


async def _run_technical(indicator_summary: str, name: str) -> AnalystVerdict:
    prompt = (
        f"Stock: {name}\n\n"
        f"Pre-computed technical indicators (1-year daily data):\n{indicator_summary}\n\n"
        "Give your independent technical verdict."
    )
    output = await technical_agent.arun(prompt)
    return output.content


async def _run_sentiment(headlines: str, name: str) -> AnalystVerdict:
    prompt = (
        f"Stock: {name}\n\n"
        f"Recent news headlines:\n{headlines}\n\n"
        "Give your independent news-sentiment verdict."
    )
    output = await sentiment_agent.arun(prompt)
    return output.content


async def _run_manager(
    name: str,
    ticker: str,
    profile: Profile,
    technical: AnalystVerdict,
    sentiment: Optional[AnalystVerdict],
):
    if sentiment is not None:
        sentiment_block = (
            f"SENTIMENT ANALYST VERDICT:\n"
            f"  signal: {sentiment.signal} (confidence {sentiment.confidence:.2f})\n"
            f"  summary: {sentiment.summary}\n"
            f"  evidence: {sentiment.evidence}\n"
            f"  caveats: {sentiment.caveats}\n"
        )
    else:
        sentiment_block = (
            "SENTIMENT ANALYST VERDICT:\n"
            "  UNAVAILABLE -- no news headlines were found for this ticker. "
            "Base your recommendation on technicals alone and say so.\n"
        )

    profile_line = (
        f"Investor profile: risk tolerance = {profile.risk_tolerance}, "
        f"horizon = {profile.horizon} "
        f"({'provided by user' if profile.tailored else 'DEFAULTED -- user did not specify'})."
    )

    prompt = (
        f"Stock: {name} ({ticker})\n"
        f"{profile_line}\n\n"
        f"TECHNICAL ANALYST VERDICT:\n"
        f"  signal: {technical.signal} (confidence {technical.confidence:.2f})\n"
        f"  summary: {technical.summary}\n"
        f"  evidence: {technical.evidence}\n"
        f"  caveats: {technical.caveats}\n\n"
        f"{sentiment_block}\n"
        "Synthesize these into your final research report."
    )
    output = await manager_agent.arun(prompt)
    return output.content


def _profile_from_intake(intake: IntakeResult) -> Profile:
    horizon_map = {"short": "short (<1y)", "medium": "medium (1-3y)", "long": "long (3y+)"}
    return Profile(
        risk_tolerance=intake.risk_tolerance,
        horizon=horizon_map.get(intake.horizon, intake.horizon),
        tailored=intake.risk_stated or intake.horizon_stated,
    )


async def _analyze_ticker(
    ticker: str, profile: Profile
) -> Union[AnalyzeComplete, AnalyzeNotFound]:
    """Run the full Tier 1 -> Tier 2 -> Tier 3 pipeline for a resolved ticker."""
    try:
        data = await asyncio.to_thread(market_data.fetch_market_data, ticker)
    except Exception as exc:
        return AnalyzeNotFound(
            message=f"Could not fetch usable market data for '{ticker}': {exc}"
        )

    headlines = await asyncio.to_thread(news.fetch_news, ticker)
    name = data["name"]

    # Tier 2: analysts run independently and in parallel.
    technical_task = _run_technical(data["indicator_summary"], name)
    if headlines:
        sentiment_task = _run_sentiment(news.headlines_text(headlines), name)
        technical, sentiment = await asyncio.gather(technical_task, sentiment_task)
    else:
        technical = await technical_task
        sentiment = None

    # Tier 3: synthesis.
    report = await _run_manager(name, ticker, profile, technical, sentiment)

    return AnalyzeComplete(
        company=name,
        ticker=ticker,
        currency=data.get("currency", ""),
        profile=profile,
        technical=technical,
        sentiment=sentiment,
        sentiment_unavailable=sentiment is None,
        report=report,
        chart=data["chart"],
        indicator_summary=data["indicator_summary"],
        headline_count=len(headlines),
    )


# --- HTTP API ---------------------------------------------------------------


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    # Fast path: the user already picked a ticker from the disambiguation list.
    if req.ticker:
        profile = _profile_from_intake(await _run_intake(req.question))
        result = await _analyze_ticker(req.ticker.strip(), profile)
        return JSONResponse(result.model_dump())

    intake = await _run_intake(req.question)
    profile = _profile_from_intake(intake)

    if not intake.companies:
        return JSONResponse(
            AnalyzeNotFound(
                message="I couldn't identify a specific company or ticker in your "
                "question. Try naming one, e.g. 'Should I invest in Apple?'"
            ).model_dump()
        )

    if len(intake.companies) > 1:
        # Offer the mentioned companies as candidates so the user picks exactly one.
        candidates = []
        for mention in intake.companies:
            matches = await asyncio.to_thread(market_data.search_candidates, mention, 1)
            if matches:
                candidates.append(matches[0])
        return JSONResponse(
            AnalyzeAmbiguous(
                message="Your question mentions more than one company. Pick the one "
                "you'd like analyzed (v1 analyzes a single stock at a time).",
                candidates=candidates,
            ).model_dump()
        )

    candidates = await asyncio.to_thread(
        market_data.search_candidates, intake.companies[0], 6
    )
    if not candidates:
        return JSONResponse(
            AnalyzeNotFound(
                message=f"No listed stock matched '{intake.companies[0]}'. "
                "Check the spelling or try a ticker symbol."
            ).model_dump()
        )

    # Unambiguous top match -> analyze it directly; otherwise ask the user.
    top = candidates[0]
    unambiguous = (
        len(candidates) == 1
        or top.name.lower() == intake.companies[0].strip().lower()
        or top.ticker.lower() == intake.companies[0].strip().lower()
    )
    if unambiguous:
        result = await _analyze_ticker(top.ticker, profile)
        return JSONResponse(result.model_dump())

    return JSONResponse(
        AnalyzeAmbiguous(
            message=f"Several stocks match '{intake.companies[0]}'. Which did you mean?",
            candidates=candidates,
        ).model_dump()
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# --- Static frontend --------------------------------------------------------

_DIST = Path(__file__).parent / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/")
    async def _index():
        return FileResponse(_DIST / "index.html")

else:
    @app.get("/")
    async def _no_build():
        return JSONResponse(
            {
                "message": "Frontend not built. Run `cd frontend && npm install && "
                "npm run build`, then restart. The API at /api/analyze works regardless."
            }
        )


# Assemble AgentOS onto our base_app *after* our routes are registered above, so
# on_route_conflict="preserve_base_app" keeps ours (notably GET /). get_app()
# mutates base_app in place and returns it.
agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="stock_service:app", port=7779, reload=True)
