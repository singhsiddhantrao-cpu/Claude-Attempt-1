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
import time
from pathlib import Path
from typing import Optional, Type, TypeVar, Union

from dotenv import load_dotenv

# Load .env and initialize agenthog FIRST -- before the model SDKs (groq, openai,
# anthropic, httpx) are imported anywhere. agenthog patches those libraries in
# place, so it must run before any client object is constructed, otherwise the
# already-built clients keep their unpatched methods and nothing is traced.
load_dotenv()

agenthog = None
AGENT_ID = os.getenv("AGENTOS_AGENT_ID", "stock-analysis")

if os.getenv("AGENTOS_API_KEY"):
    import agenthog as _agenthog

    agenthog = _agenthog
    agenthog.init(agent_id=AGENT_ID)
    _traced = agenthog.autoinstrument()
    print(
        f"AGENTOS_API_KEY detected -- tracing to theagentos.space as '{AGENT_ID}' "
        f"(auto-instrumented: {', '.join(_traced) or 'none'}; agent calls are also "
        f"traced explicitly)."
    )
else:
    print(
        "AGENTOS_API_KEY not set -- skipping agenthog instrumentation "
        "(nothing sent to theagentos.space). See .env.example."
    )

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from stock_analysis.agents import (  # noqa: E402
    build_intake_agent,
    build_manager_agent,
    build_sentiment_agent,
    build_technical_agent,
)
from stock_analysis.schemas import (  # noqa: E402
    AnalyzeAmbiguous,
    AnalyzeComplete,
    AnalyzeNotFound,
    AnalyzeRequest,
    AnalystVerdict,
    FinalReport,
    IntakeResult,
    Profile,
)
from stock_analysis.tools import market_data, news  # noqa: E402

if not (
    os.getenv("GROQ_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or os.getenv("NVIDIA_API_KEY")
    or os.getenv("ANTHROPIC_API_KEY")
):
    raise RuntimeError(
        "No model provider key is set. Copy .env.example to .env and set ONE of: "
        "GROQ_API_KEY (free, https://console.groq.com), GOOGLE_API_KEY (free, "
        "https://aistudio.google.com), NVIDIA_API_KEY (free, https://build.nvidia.com), "
        "or ANTHROPIC_API_KEY (Claude, needs prepaid credit)."
    )

if os.getenv("GROQ_API_KEY"):
    print("GROQ_API_KEY detected -- using Groq's free models (console.groq.com).")
elif os.getenv("GOOGLE_API_KEY"):
    print("GOOGLE_API_KEY detected -- using Google's free Gemini models (aistudio.google.com).")
elif os.getenv("NVIDIA_API_KEY"):
    print("NVIDIA_API_KEY detected -- using NVIDIA's free models (build.nvidia.com).")

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

# Hard per-call ceiling (seconds). Even if the model client's own timeout/retry
# misbehaves, this aborts a stuck agent call and returns a readable message
# instead of the request hanging forever. Overridable via .env.
_CALL_TIMEOUT = float(os.getenv("AGENT_TIMEOUT_SECONDS", "90"))

# Which tier of the architecture each agent belongs to. Recorded on the trace so
# the dashboard shows the pipeline's shape, not just four interchangeable calls.
_TIERS = {
    "intake": "tier0-intake",
    "technical-analyst": "tier2-analyst",
    "sentiment-analyst": "tier2-analyst",
    "portfolio-manager": "tier3-manager",
}

_T = TypeVar("_T", bound=BaseModel)


def _trace_llm_call(agent, prompt, output, started, error=None):
    """Emit an agent.llm_call event to theagentos.space for one agent run.

    We trace explicitly rather than relying on agenthog's auto-instrumentation:
    its httpx hook deliberately skips requests carrying x-stainless-* headers
    (assuming a dedicated vendor integration covers them), and Groq's SDK sends
    those headers but has no such integration -- so Groq calls would otherwise
    be captured by nothing. Doing it here also makes the trace provider-agnostic
    and lets us label each span with the agent's role.
    """
    if agenthog is None:
        return
    duration_ms = (time.perf_counter() - started) * 1000
    model = getattr(agent.model, "id", "unknown")
    provider = type(agent.model).__name__.lower()
    metrics = getattr(output, "metrics", None) if output is not None else None
    content = str(output.content) if output is not None else None
    # Each agent gets its own agent_id so the dashboard's agent filter and
    # Agent Graph can tell the four tiers apart, rather than lumping every call
    # under one id.
    role_agent_id = f"{AGENT_ID}.{agent.name}"

    if error is None:
        status = "success"
    elif error.get("type") == "timeout":
        status = "timeout"
    else:
        status = "error"

    client = agenthog.get_default_client()
    # A child span keeps this agent's events grouped together under the run.
    # The two emits are guarded separately so a rejected field in one can never
    # swallow the other -- the failure mode that first hid these traces.
    try:
        with agenthog.start_span(agent.name, kind="agent"):
            # LLM spans are labelled by model name, so four agents sharing a
            # model look identical. This named tool_call span carries the
            # agent's role as its label, with the llm_call alongside it.
            try:
                client.log_tool_call(
                    name=agent.name,
                    input={"prompt": str(prompt)[:4000]},
                    output={"response": content[:4000]} if content else None,
                    status=status,
                    duration_ms=duration_ms,
                    error=error,
                    agent_id=role_agent_id,
                )
            except Exception as exc:
                print(f"[trace] tool_call span failed for {agent.name}: {exc}")

            try:
                client.log_llm_call(
                    model=model,
                    system=provider,
                    input=[{"role": "user", "content": str(prompt)}],
                    output=[{"role": "assistant", "content": content}] if content else None,
                    input_tokens=getattr(metrics, "input_tokens", None),
                    output_tokens=getattr(metrics, "output_tokens", None),
                    total_tokens=getattr(metrics, "total_tokens", None),
                    duration_ms=duration_ms,
                    error=error,
                    agent_id=role_agent_id,
                    agent_role=agent.name,
                    agent_tier=_TIERS.get(agent.name, "unknown"),
                )
            except Exception as exc:
                print(f"[trace] llm_call span failed for {agent.name}: {exc}")
    except Exception as exc:  # never let tracing break the analysis
        print(f"[trace] could not log run for {agent.name}: {exc}")


async def _arun(agent, prompt):
    """Run one agent with a hard timeout so a stuck call can't hang the request."""
    started = time.perf_counter()
    try:
        output = await asyncio.wait_for(agent.arun(prompt), timeout=_CALL_TIMEOUT)
    except asyncio.TimeoutError:
        _trace_llm_call(
            agent, prompt, None, started, error={"type": "timeout", "message": "aborted"}
        )
        raise ValueError(
            f"A model call took longer than {_CALL_TIMEOUT:.0f}s and was aborted -- "
            "usually free-tier rate limiting or an overloaded model. Wait a few "
            "seconds and try again, or set a faster model in .env "
            "(e.g. ANALYST_MODEL=meta/llama-3.1-8b-instruct)."
        )
    except Exception as exc:
        _trace_llm_call(
            agent, prompt, None, started, error={"type": type(exc).__name__, "message": str(exc)[:300]}
        )
        raise
    _trace_llm_call(agent, prompt, output, started)
    return output


def _coerce(content, model_cls: Type[_T]) -> _T:
    """Turn an agent's output into ``model_cls``, whatever shape it arrived in.

    Agno usually parses ``output_schema`` into the Pydantic model for us, but if
    the model replies with slightly-off JSON (or prose wrapping JSON) it silently
    leaves ``content`` as a raw string. We handle every case here so a stray
    string can't crash the pipeline: already-a-model, a dict, clean JSON, or JSON
    embedded in surrounding text.
    """
    if isinstance(content, model_cls):
        return content
    if isinstance(content, dict):
        return model_cls.model_validate(content)
    if isinstance(content, str):
        text = content.strip()
        # The model layer sometimes hands back an Anthropic API *error* payload
        # (e.g. {'type': 'error', 'error': {...}}) instead of an answer. Surface
        # that verbatim -- it's the real problem (no credit, bad key, model not
        # available), not a parsing bug.
        if "'type': 'error'" in text or '"type": "error"' in text:
            print(f"[analyze] Anthropic API error in agent output: {text}")
            raise ValueError(
                "The Anthropic API returned an error instead of an analysis. This "
                "usually means the account is out of credit, the API key is invalid, "
                "or the model isn't available to your account. Full error: " + text
            )
        try:
            return model_cls.model_validate_json(text)
        except (ValidationError, ValueError):
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                return model_cls.model_validate_json(text[start : end + 1])
    raise ValueError(
        f"The model did not return valid {model_cls.__name__} data. "
        f"Got {type(content).__name__}: {str(content)[:200]}"
    )


async def _run_intake(question: str) -> IntakeResult:
    output = await _arun(intake_agent, question)
    try:
        return _coerce(output.content, IntakeResult)
    except (ValidationError, ValueError):
        # Fall back to treating the whole question as one company mention.
        return IntakeResult(companies=[question])


async def _run_technical(indicator_summary: str, name: str) -> AnalystVerdict:
    prompt = (
        f"Stock: {name}\n\n"
        f"Pre-computed technical indicators (1-year daily data):\n{indicator_summary}\n\n"
        "Give your independent technical verdict."
    )
    output = await _arun(technical_agent, prompt)
    return _coerce(output.content, AnalystVerdict)


async def _run_sentiment(headlines: str, name: str) -> AnalystVerdict:
    prompt = (
        f"Stock: {name}\n\n"
        f"Recent news headlines:\n{headlines}\n\n"
        "Give your independent news-sentiment verdict."
    )
    output = await _arun(sentiment_agent, prompt)
    return _coerce(output.content, AnalystVerdict)


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
    output = await _arun(manager_agent, prompt)
    return _coerce(output.content, FinalReport)


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
    # Wrap the whole pipeline so an unexpected failure (bad model output, a
    # yfinance hiccup, an API error) comes back as a readable message the SPA can
    # show, instead of an opaque HTTP 500. The full traceback still prints to the
    # server console for debugging.
    if agenthog is not None:
        # Group this analysis's four agent calls under one task_run so they show
        # up on theagentos.space as a single trace rather than loose events.
        with agenthog.start_task_run(agent_id=AGENT_ID):
            try:
                result = await _handle_analyze(req)
            except Exception as exc:
                import traceback

                traceback.print_exc()
                result = JSONResponse(
                    {"status": "error", "message": f"Analysis failed: {exc}"}
                )
            # Ship the batch now instead of waiting for the periodic flush, so
            # traces appear on the dashboard right after the run finishes.
            try:
                agenthog.flush()
            except Exception:
                pass
            return result

    try:
        return await _handle_analyze(req)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        return JSONResponse(
            {"status": "error", "message": f"Analysis failed: {exc}"}
        )


async def _handle_analyze(req: AnalyzeRequest):
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
