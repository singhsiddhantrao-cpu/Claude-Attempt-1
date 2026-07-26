"""Unit tests for the Tier-1 tools (market_data, news).

These use synthetic data only -- no network. They lock in the two things that
must not silently break: the indicator/chart output is JSON-safe (no NaN/inf),
and the defensive news parsing handles both Yahoo payload shapes.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import math
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from stock_analysis.schemas import TickerCandidate
from stock_analysis.tools import market_data, news


def _synthetic_history(days: int = 260, seed: int = 0) -> pd.DataFrame:
    """A deterministic 1y-ish daily OHLCV frame shaped like yfinance's output."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=days, freq="B")
    # A gently trending random walk so indicators have something to chew on.
    steps = rng.normal(0.4, 2.0, size=days)
    close = 100 + np.cumsum(steps)
    close = np.clip(close, 1.0, None)
    volume = rng.integers(1_000_000, 5_000_000, size=days).astype(float)
    return pd.DataFrame({"Close": close, "Volume": volume}, index=idx)


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.history = _synthetic_history()

    def test_compute_indicators_are_json_safe(self):
        ind = market_data.compute_indicators(self.history)
        # Every numeric field must be a real float or None -- never NaN/inf,
        # because those break JSON serialization to the frontend.
        for key, value in ind.items():
            if isinstance(value, float):
                self.assertFalse(math.isnan(value), f"{key} is NaN")
                self.assertFalse(math.isinf(value), f"{key} is inf")
        # And the whole dict must actually serialize.
        json.dumps(ind)

    def test_last_close_matches_input(self):
        ind = market_data.compute_indicators(self.history)
        self.assertAlmostEqual(
            ind["last_close"], float(self.history["Close"].iloc[-1]), places=4
        )

    def test_rsi_in_range(self):
        ind = market_data.compute_indicators(self.history)
        self.assertIsNotNone(ind["rsi14"])
        self.assertGreaterEqual(ind["rsi14"], 0.0)
        self.assertLessEqual(ind["rsi14"], 100.0)

    def test_cross_state_is_known_value(self):
        ind = market_data.compute_indicators(self.history)
        self.assertIn(
            ind["moving_average_cross"],
            {"none", "golden_cross", "death_cross", "sma50_above_sma200", "sma50_below_sma200"},
        )

    def test_too_short_history_raises(self):
        with self.assertRaises(ValueError):
            market_data.compute_indicators(self.history.head(10))

    def test_indicator_summary_is_text(self):
        ind = market_data.compute_indicators(self.history)
        summary = market_data.indicator_summary(ind, currency="USD")
        self.assertIn("RSI(14)", summary)
        self.assertIn("USD", summary)

    def test_build_chart_json_safe_and_aligned(self):
        chart = market_data.build_chart(self.history, max_points=180)
        n = len(chart.dates)
        self.assertTrue(0 < n <= 260)
        # All series share the date axis length.
        self.assertEqual(len(chart.close), n)
        self.assertEqual(len(chart.volume), n)
        self.assertEqual(len(chart.sma50), n)
        self.assertEqual(len(chart.sma200), n)
        # Serializes cleanly (Optional[float], no NaN).
        json.dumps(chart.model_dump())


class SearchCandidateTests(unittest.TestCase):
    def _fake_search(self, quotes):
        m = mock.MagicMock()
        m.quotes = quotes
        return m

    def test_exact_symbol_match_ranks_first(self):
        quotes = [
            {"symbol": "AAPLW", "shortname": "Apple Warrant", "quoteType": "EQUITY", "exchDisp": "NYSE"},
            {"symbol": "AAPL", "shortname": "Apple Inc.", "quoteType": "EQUITY", "exchDisp": "NASDAQ"},
        ]
        with mock.patch.object(market_data.yf, "Search", return_value=self._fake_search(quotes)):
            out = market_data.search_candidates("AAPL")
        self.assertEqual(out[0].ticker, "AAPL")
        self.assertIsInstance(out[0], TickerCandidate)

    def test_non_equity_types_filtered(self):
        quotes = [
            {"symbol": "^GSPC", "shortname": "S&P 500", "quoteType": "INDEX"},
            {"symbol": "SPY", "shortname": "SPDR S&P 500 ETF", "quoteType": "ETF", "exchDisp": "NYSE"},
        ]
        with mock.patch.object(market_data.yf, "Search", return_value=self._fake_search(quotes)):
            out = market_data.search_candidates("s&p 500")
        self.assertEqual([c.ticker for c in out], ["SPY"])

    def test_dedup_and_search_failure(self):
        quotes = [
            {"symbol": "TCS.NS", "longname": "Tata Consultancy Services", "quoteType": "EQUITY", "exchDisp": "NSE"},
            {"symbol": "TCS.NS", "longname": "Tata Consultancy Services", "quoteType": "EQUITY", "exchDisp": "NSE"},
        ]
        with mock.patch.object(market_data.yf, "Search", return_value=self._fake_search(quotes)):
            out = market_data.search_candidates("tcs")
        self.assertEqual(len(out), 1)
        # A raised search error degrades to an empty list, never an exception.
        with mock.patch.object(market_data.yf, "Search", side_effect=RuntimeError("boom")):
            self.assertEqual(market_data.search_candidates("whatever"), [])


class NewsParsingTests(unittest.TestCase):
    def test_extract_new_nested_shape(self):
        article = {
            "content": {
                "title": "Company beats earnings",
                "summary": "Strong quarter.",
                "pubDate": "2024-05-01T00:00:00Z",
                "provider": {"displayName": "Reuters"},
            }
        }
        item = news._extract(article)
        self.assertEqual(item["title"], "Company beats earnings")
        self.assertEqual(item["publisher"], "Reuters")
        self.assertEqual(item["summary"], "Strong quarter.")

    def test_extract_old_flat_shape(self):
        article = {
            "title": "Old-style headline",
            "summary": "Body.",
            "publisher": "Bloomberg",
            "providerPublishTime": 1714521600,
        }
        item = news._extract(article)
        self.assertEqual(item["title"], "Old-style headline")
        self.assertEqual(item["publisher"], "Bloomberg")

    def test_extract_missing_title_is_dropped(self):
        self.assertIsNone(news._extract({"content": {"summary": "no title"}}))

    def test_fetch_news_dedups_and_survives_errors(self):
        raw = [
            {"content": {"title": "Dup", "provider": {"displayName": "X"}}},
            {"content": {"title": "dup", "provider": {"displayName": "Y"}}},  # case-insensitive dup
            {"content": {"title": "Unique", "provider": {"displayName": "Z"}}},
        ]
        fake_tk = mock.MagicMock()
        fake_tk.get_news.return_value = raw
        with mock.patch.object(news.yf, "Ticker", return_value=fake_tk):
            out = news.fetch_news("AAPL")
        self.assertEqual(len(out), 2)

        with mock.patch.object(news.yf, "Ticker", side_effect=RuntimeError("down")):
            self.assertEqual(news.fetch_news("AAPL"), [])

    def test_headlines_text_empty_and_populated(self):
        self.assertIn("no headlines", news.headlines_text([]))
        text = news.headlines_text(
            [{"title": "T", "publisher": "P", "date": "2024", "summary": "S"}]
        )
        self.assertIn("1. T", text)
        self.assertIn("P", text)


if __name__ == "__main__":
    unittest.main()
