"""Pydantic models shared across the pipeline and the HTTP API.

The analyst and manager schemas double as the agents' ``output_schema`` (so the
LLM output is validated into these types) *and* as the JSON the API returns to
the frontend.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Signal = Literal["bullish", "bearish", "neutral"]
Rating = Literal["favorable", "neutral", "unfavorable"]


# --- Intake -----------------------------------------------------------------


class IntakeResult(BaseModel):
    """Structured extraction from the user's free-text question."""

    companies: list[str] = Field(
        default_factory=list,
        description="Company names or ticker symbols the user mentioned, in the "
        "order they appeared. Empty if none could be identified.",
    )
    risk_tolerance: Literal["conservative", "moderate", "aggressive"] = Field(
        "moderate",
        description="The user's stated or clearly implied risk tolerance. "
        "Default to 'moderate' when unstated.",
    )
    horizon: Literal["short", "medium", "long"] = Field(
        "long",
        description="Investment horizon: short (<1y), medium (1-3y), long (3y+). "
        "Default to 'long' when unstated.",
    )
    horizon_stated: bool = Field(
        False, description="True only if the user explicitly stated a horizon."
    )
    risk_stated: bool = Field(
        False, description="True only if the user explicitly stated a risk tolerance."
    )


# --- Ticker resolution ------------------------------------------------------


class TickerCandidate(BaseModel):
    ticker: str
    name: str
    exchange: str = ""


# --- Analyst verdicts (Tier 2) ---------------------------------------------


class AnalystVerdict(BaseModel):
    """A single analyst's independent read. Both analysts share this shape."""

    signal: Signal = Field(description="Overall directional read from this analyst.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in the signal, 0.0 to 1.0."
    )
    summary: str = Field(description="One or two sentences stating the read.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Specific data points from the provided data that support the "
        "signal. Do not cite anything not present in the data.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Limitations of this read (e.g. thin data, mixed indicators).",
    )


# --- Final report (Tier 3) --------------------------------------------------


class FinalReport(BaseModel):
    """The Portfolio Manager's synthesized recommendation."""

    rating: Rating = Field(
        description="Overall stance for the stated investor profile and horizon."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="A short plain-language bottom line.")
    key_reasons: list[str] = Field(
        default_factory=list, description="The main points supporting the rating."
    )
    key_risks: list[str] = Field(
        default_factory=list, description="The main risks to the rating."
    )
    what_would_change_this: list[str] = Field(
        default_factory=list,
        description="Concrete developments that would move the rating up or down.",
    )
    disclaimer: str = Field(
        description="A clear not-financial-advice disclaimer, including that this "
        "analysis covers only technicals and news sentiment (no fundamentals)."
    )


# --- HTTP API ---------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1)
    ticker: Optional[str] = Field(
        None,
        description="A resolved ticker, sent when the user picks from the "
        "disambiguation list. Skips intake/resolution when present.",
    )


class ChartSeries(BaseModel):
    dates: list[str]
    close: list[Optional[float]]
    volume: list[Optional[float]]
    sma50: list[Optional[float]]
    sma200: list[Optional[float]]


class Profile(BaseModel):
    risk_tolerance: str
    horizon: str
    tailored: bool = Field(
        description="True if the profile came from the user; False if defaulted."
    )


class AnalyzeComplete(BaseModel):
    status: Literal["complete"] = "complete"
    company: str
    ticker: str
    currency: str = ""
    profile: Profile
    technical: AnalystVerdict
    sentiment: Optional[AnalystVerdict] = Field(
        None, description="None when no news was available for the ticker."
    )
    sentiment_unavailable: bool = False
    report: FinalReport
    chart: ChartSeries
    indicator_summary: str = Field(
        description="The plain-text indicator table the Technical Analyst read."
    )
    headline_count: int = 0


class AnalyzeAmbiguous(BaseModel):
    status: Literal["ambiguous"] = "ambiguous"
    message: str
    candidates: list[TickerCandidate]


class AnalyzeNotFound(BaseModel):
    status: Literal["not_found"] = "not_found"
    message: str
