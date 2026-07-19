"""The four agents of the pipeline, built as Agno ``Agent`` instances.

Tier assignment and models (per the system design):
  - Intake            (Tier 0 helper) -- claude-sonnet-5, structured extraction
  - Technical Analyst (Tier 2)        -- claude-sonnet-5
  - Sentiment Analyst (Tier 2)        -- claude-sonnet-5
  - Portfolio Manager (Tier 3)        -- claude-opus-4-8, the synthesis / judgment call

Each agent has an ``output_schema`` so Agno validates the model output into the
Pydantic types in ``schemas.py``. They are created once and registered with
AgentOS in ``stock_service.py`` for tracing.
"""

from __future__ import annotations

from agno.agent import Agent
from agno.models.anthropic import Claude

from stock_analysis.schemas import AnalystVerdict, FinalReport, IntakeResult

ANALYST_MODEL = "claude-sonnet-5"
MANAGER_MODEL = "claude-opus-4-8"


def build_intake_agent(db=None) -> Agent:
    return Agent(
        name="intake",
        model=Claude(id=ANALYST_MODEL),
        db=db,
        output_schema=IntakeResult,
        description="You extract structured intent from an investor's free-text question.",
        instructions=[
            "Identify every company or ticker the user mentions, in order.",
            "A 'company' is a listed business or fund the user wants analyzed. Ignore "
            "indices, sectors, or people.",
            "Extract risk tolerance and horizon ONLY if the user states or clearly "
            "implies them; otherwise leave the defaults and set the *_stated flags false.",
            "Do not guess ticker symbols; just report the names/symbols as written.",
        ],
    )


TECHNICAL_INSTRUCTIONS = [
    "You are a technical analyst. You are given a table of pre-computed technical "
    "indicators for one stock over the past year. The numbers are already correct -- "
    "your job is ONLY to interpret them, never to recompute or estimate.",
    "Base your read exclusively on the indicators provided. Do NOT use any outside "
    "knowledge about the company, its fundamentals, or recent events. If you catch "
    "yourself citing something not in the table, remove it.",
    "Weigh trend (price vs SMA50/SMA200, moving-average cross), momentum (RSI, MACD), "
    "position in the 52-week range, and volatility/volume. Note when signals conflict.",
    "Every item in 'evidence' must reference a specific figure from the table.",
    "Put genuine limitations in 'caveats' (e.g. mixed signals, extended RSI, thin trend).",
    "This is a long-horizon read: favor the SMA200 / multi-month trend over day-to-day noise.",
]

SENTIMENT_INSTRUCTIONS = [
    "You are a news-sentiment analyst. You are given a list of recent headlines and "
    "summaries for one stock. Judge the tone and likely market impact of THIS news only.",
    "Base your read exclusively on the headlines provided. Do NOT use outside knowledge "
    "about the company or its price history.",
    "Every item in 'evidence' must reference a specific headline.",
    "If there are few headlines, or they are stale, off-topic, or mixed, say so in "
    "'caveats' and lower your confidence accordingly. Thin coverage is common for "
    "non-US listings.",
    "Distinguish routine coverage from genuinely market-moving news.",
]


def build_technical_agent(db=None) -> Agent:
    return Agent(
        name="technical-analyst",
        model=Claude(id=ANALYST_MODEL),
        db=db,
        output_schema=AnalystVerdict,
        description="You read pre-computed technical indicators and give a directional verdict.",
        instructions=TECHNICAL_INSTRUCTIONS,
    )


def build_sentiment_agent(db=None) -> Agent:
    return Agent(
        name="sentiment-analyst",
        model=Claude(id=ANALYST_MODEL),
        db=db,
        output_schema=AnalystVerdict,
        description="You read recent news headlines and give a sentiment verdict.",
        instructions=SENTIMENT_INSTRUCTIONS,
    )


MANAGER_INSTRUCTIONS = [
    "You are a portfolio manager. Two independent analysts have each produced a verdict "
    "for one stock: a technical analyst (price indicators) and, when news was available, "
    "a sentiment analyst (recent headlines). You synthesize them into one recommendation "
    "for the specified investor profile and horizon.",
    "The two analysts did NOT see each other's work. When they disagree, resolve the "
    "conflict explicitly in your reasoning and reflect the uncertainty in your confidence.",
    "Tailor the rating to the investor's risk tolerance and horizon. State the profile "
    "you assumed if it was defaulted rather than provided.",
    "Rate 'favorable', 'neutral', or 'unfavorable' -- a stance on whether the stock merits "
    "consideration for this investor, NOT a buy/sell order.",
    "If sentiment data was unavailable, say the recommendation rests on technicals alone.",
    "The 'disclaimer' field is REQUIRED and must state clearly: (1) this is not financial "
    "advice and is for informational purposes only, and (2) this analysis covers only price "
    "technicals and news sentiment -- it does NOT consider fundamentals (earnings, valuation, "
    "debt, competitive position), which are essential for a real long-term decision.",
    "Keep 'key_reasons', 'key_risks', and 'what_would_change_this' concrete and grounded in "
    "the analyst verdicts you were given.",
]


def build_manager_agent(db=None) -> Agent:
    return Agent(
        name="portfolio-manager",
        model=Claude(id=MANAGER_MODEL),
        db=db,
        output_schema=FinalReport,
        description="You synthesize analyst verdicts into a final investment-research report.",
        instructions=MANAGER_INSTRUCTIONS,
    )
