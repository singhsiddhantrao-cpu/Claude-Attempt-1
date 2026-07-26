"""Route-logic tests for stock_service, with agents and yfinance fully mocked.

The real pipeline needs an Anthropic key + live Yahoo Finance; neither is
available in CI/sandbox. So we set a dummy key, import the app, then patch the
module-level agents and Tier-1 tools to exercise the branching in POST
/api/analyze deterministically:

  - complete (unambiguous single company)
  - ambiguous (two companies named)
  - ambiguous (one name, several matches -> "did you mean")
  - not_found (no company / no match)
  - no-news (sentiment analyst skipped)
  - static / serves the SPA

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-dummy-for-tests")

from fastapi.testclient import TestClient  # noqa: E402

import stock_service as svc  # noqa: E402
from stock_analysis.schemas import (  # noqa: E402
    AnalystVerdict,
    ChartSeries,
    FinalReport,
    IntakeResult,
    TickerCandidate,
)


def _agent_returning(value):
    """An object whose .arun(...) awaits to a result with .content == value."""
    agent = mock.MagicMock()

    async def _arun(*_args, **_kwargs):
        out = mock.MagicMock()
        out.content = value
        return out

    agent.arun = _arun
    return agent


def _verdict(signal="bullish"):
    return AnalystVerdict(
        signal=signal, confidence=0.7, summary="ok", evidence=["e"], caveats=["c"]
    )


def _report():
    return FinalReport(
        rating="favorable",
        confidence=0.6,
        summary="bottom line",
        key_reasons=["r"],
        key_risks=["k"],
        what_would_change_this=["w"],
        disclaimer="Not financial advice. Technicals + sentiment only, no fundamentals.",
    )


def _market_data(name="Apple Inc.", currency="USD"):
    return {
        "ticker": "AAPL",
        "name": name,
        "currency": currency,
        "exchange": "NMS",
        "indicators": {},
        "indicator_summary": "RSI(14): 55.00",
        "chart": ChartSeries(dates=["2024-01-01"], close=[100.0], volume=[1.0], sma50=[None], sma200=[None]),
    }


class AnalyzeRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(svc.app)

    def _patch_agents(self, intake, technical=None, sentiment=None, report=None):
        return mock.patch.multiple(
            svc,
            intake_agent=_agent_returning(intake),
            technical_agent=_agent_returning(technical or _verdict()),
            sentiment_agent=_agent_returning(sentiment or _verdict("neutral")),
            manager_agent=_agent_returning(report or _report()),
        )

    def test_complete_unambiguous(self):
        intake = IntakeResult(companies=["Apple"], risk_tolerance="moderate", horizon="long")
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "search_candidates",
                               return_value=[TickerCandidate(ticker="AAPL", name="Apple Inc.", exchange="NMS")]), \
             mock.patch.object(svc.market_data, "fetch_market_data", return_value=_market_data()), \
             mock.patch.object(svc.news, "fetch_news", return_value=[{"title": "t", "publisher": "p", "date": "2024", "summary": "s"}]), \
             mock.patch.object(svc.news, "headlines_text", return_value="1. t"):
            r = self.client.post("/api/analyze", json={"question": "Should I buy Apple?"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "complete")
        self.assertEqual(body["ticker"], "AAPL")
        self.assertEqual(body["report"]["rating"], "favorable")
        self.assertFalse(body["sentiment_unavailable"])
        self.assertIsNotNone(body["sentiment"])

    def test_no_news_skips_sentiment(self):
        intake = IntakeResult(companies=["Apple"])
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "search_candidates",
                               return_value=[TickerCandidate(ticker="AAPL", name="Apple Inc.")]), \
             mock.patch.object(svc.market_data, "fetch_market_data", return_value=_market_data()), \
             mock.patch.object(svc.news, "fetch_news", return_value=[]):
            r = self.client.post("/api/analyze", json={"question": "Apple?"})
        body = r.json()
        self.assertEqual(body["status"], "complete")
        self.assertTrue(body["sentiment_unavailable"])
        self.assertIsNone(body["sentiment"])
        self.assertEqual(body["headline_count"], 0)

    def test_two_companies_ambiguous(self):
        intake = IntakeResult(companies=["Apple", "Microsoft"])
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "search_candidates",
                               side_effect=lambda q, n=1: [TickerCandidate(ticker=q[:4].upper(), name=q)]):
            r = self.client.post("/api/analyze", json={"question": "Apple or Microsoft?"})
        body = r.json()
        self.assertEqual(body["status"], "ambiguous")
        self.assertEqual(len(body["candidates"]), 2)

    def test_single_name_multiple_matches_ambiguous(self):
        intake = IntakeResult(companies=["Reliance"])
        matches = [
            TickerCandidate(ticker="RELIANCE.NS", name="Reliance Industries", exchange="NSE"),
            TickerCandidate(ticker="RPOWER.NS", name="Reliance Power", exchange="NSE"),
        ]
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "search_candidates", return_value=matches):
            r = self.client.post("/api/analyze", json={"question": "Should I buy Reliance?"})
        body = r.json()
        self.assertEqual(body["status"], "ambiguous")
        self.assertEqual(len(body["candidates"]), 2)

    def test_no_company_not_found(self):
        intake = IntakeResult(companies=[])
        with self._patch_agents(intake):
            r = self.client.post("/api/analyze", json={"question": "what is the weather?"})
        self.assertEqual(r.json()["status"], "not_found")

    def test_no_match_not_found(self):
        intake = IntakeResult(companies=["Zzzznotarealco"])
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "search_candidates", return_value=[]):
            r = self.client.post("/api/analyze", json={"question": "buy Zzzznotarealco?"})
        self.assertEqual(r.json()["status"], "not_found")

    def test_ticker_fast_path_skips_resolution(self):
        intake = IntakeResult(companies=["Apple"])
        with self._patch_agents(intake), \
             mock.patch.object(svc.market_data, "fetch_market_data", return_value=_market_data()) as fetch, \
             mock.patch.object(svc.market_data, "search_candidates") as search, \
             mock.patch.object(svc.news, "fetch_news", return_value=[]):
            r = self.client.post("/api/analyze", json={"question": "this one", "ticker": "AAPL"})
        self.assertEqual(r.json()["status"], "complete")
        fetch.assert_called_once()
        search.assert_not_called()  # ticker provided -> no resolution search


class CoerceAndErrorTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(svc.app)

    def test_coerce_accepts_model_dict_and_json(self):
        v = AnalystVerdict(signal="bullish", confidence=0.5, summary="x")
        self.assertIs(svc._coerce(v, AnalystVerdict), v)
        self.assertEqual(
            svc._coerce({"signal": "bearish", "confidence": 0.3, "summary": "y"}, AnalystVerdict).signal,
            "bearish",
        )
        self.assertEqual(
            svc._coerce('{"signal":"neutral","confidence":0.4,"summary":"z"}', AnalystVerdict).signal,
            "neutral",
        )
        # JSON embedded in surrounding prose (the exact failure mode we hit live).
        self.assertEqual(
            svc._coerce('Sure:\n{"signal":"bullish","confidence":0.9,"summary":"w"} done', AnalystVerdict).confidence,
            0.9,
        )

    def test_coerce_raises_on_garbage(self):
        with self.assertRaises(ValueError):
            svc._coerce("this is not json at all", AnalystVerdict)

    def test_pipeline_exception_becomes_error_status_not_500(self):
        # An agent blowing up should surface as a readable message, not HTTP 500.
        boom = mock.MagicMock()

        async def _raise(*_a, **_k):
            raise RuntimeError("model exploded")

        boom.arun = _raise
        with mock.patch.object(svc, "intake_agent", boom):
            r = self.client.post("/api/analyze", json={"question": "Apple?"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "error")
        self.assertIn("model exploded", body["message"])


class StaticServingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(svc.app)

    def test_root_serves_spa_not_agentos_json(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("id=\"root\"", r.text)

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
