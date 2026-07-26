"""Tier 1: deterministic market data and technical indicators.

Everything here is pure Python (yfinance + pandas). No LLM is involved -- the
indicators are computed exactly so the Technical Analyst only has to *interpret*
them, never compute them.

Network calls go to Yahoo Finance's public endpoints via yfinance (no API key).
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd
import yfinance as yf

from stock_analysis.schemas import ChartSeries, TickerCandidate

# Quote types we treat as analyzable equities/funds.
_EQUITY_TYPES = {"EQUITY", "ETF"}


def _clean(value) -> Optional[float]:
    """Return a JSON-safe float (None for NaN/inf), else None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def search_candidates(query: str, max_results: int = 6) -> list[TickerCandidate]:
    """Search Yahoo Finance for equities matching a name or symbol.

    Returns candidates ranked so an exact name/symbol match floats to the top,
    then by whether Yahoo already ranked it highly. Used both to auto-resolve an
    unambiguous query and to present a "did you mean..." picker.
    """
    try:
        quotes = yf.Search(query, max_results=max_results, news_count=0).quotes
    except Exception:
        return []

    q_lower = query.strip().lower()
    candidates: list[tuple[int, TickerCandidate]] = []
    seen: set[str] = set()

    for quote in quotes:
        if quote.get("quoteType") not in _EQUITY_TYPES:
            continue
        symbol = (quote.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        name = (
            quote.get("longname")
            or quote.get("shortname")
            or quote.get("name")
            or symbol
        )
        exchange = quote.get("exchDisp") or quote.get("exchange") or ""

        # Rank: 0 = exact symbol/name match, 1 = name starts with query, 2 = other.
        rank = 2
        if symbol.lower() == q_lower or name.lower() == q_lower:
            rank = 0
        elif name.lower().startswith(q_lower) or symbol.lower().startswith(q_lower):
            rank = 1
        candidates.append((rank, TickerCandidate(ticker=symbol, name=name, exchange=exchange)))

    candidates.sort(key=lambda pair: pair[0])
    return [candidate for _rank, candidate in candidates]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line


def compute_indicators(history: pd.DataFrame) -> dict:
    """Compute technical indicators from a 1y daily OHLCV frame.

    ``history`` must have a DatetimeIndex and 'Close'/'Volume' columns (the shape
    yfinance's ``Ticker.history`` returns). Raises ValueError if too short.
    """
    if history is None or history.empty or len(history) < 30:
        raise ValueError("not enough price history to compute indicators")

    close = history["Close"].astype(float)
    volume = history["Volume"].astype(float)

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    rsi = _rsi(close)
    macd_line, macd_signal = _macd(close)

    last_close = close.iloc[-1]
    high_52w = close.max()
    low_52w = close.min()

    # Annualized volatility from daily log returns.
    log_returns = (close / close.shift(1)).apply(lambda x: math.log(x) if x > 0 else 0)
    daily_vol = log_returns.tail(min(len(log_returns), 60)).std()
    annual_vol = daily_vol * math.sqrt(252) if daily_vol else None

    recent_vol_avg = volume.tail(20).mean()
    prior_vol_avg = volume.tail(60).head(40).mean() if len(volume) >= 60 else None
    volume_trend = None
    if recent_vol_avg and prior_vol_avg and prior_vol_avg > 0:
        volume_trend = (recent_vol_avg / prior_vol_avg - 1) * 100

    def pct_from(level) -> Optional[float]:
        lvl = _clean(level)
        if lvl is None or lvl == 0:
            return None
        return (last_close / lvl - 1) * 100

    # Golden/death cross detection over the last ~10 sessions.
    cross = "none"
    if not sma50.tail(10).isna().all() and not sma200.tail(10).isna().all():
        diff = (sma50 - sma200).tail(10).dropna()
        if len(diff) >= 2:
            if diff.iloc[0] < 0 and diff.iloc[-1] > 0:
                cross = "golden_cross"
            elif diff.iloc[0] > 0 and diff.iloc[-1] < 0:
                cross = "death_cross"
            elif diff.iloc[-1] > 0:
                cross = "sma50_above_sma200"
            else:
                cross = "sma50_below_sma200"

    return {
        "last_close": _clean(last_close),
        "sma20": _clean(sma20.iloc[-1]),
        "sma50": _clean(sma50.iloc[-1]),
        "sma200": _clean(sma200.iloc[-1]),
        "pct_vs_sma50": pct_from(sma50.iloc[-1]),
        "pct_vs_sma200": pct_from(sma200.iloc[-1]),
        "rsi14": _clean(rsi.iloc[-1]),
        "macd": _clean(macd_line.iloc[-1]),
        "macd_signal": _clean(macd_signal.iloc[-1]),
        "macd_above_signal": (
            None
            if _clean(macd_line.iloc[-1]) is None or _clean(macd_signal.iloc[-1]) is None
            else bool(macd_line.iloc[-1] > macd_signal.iloc[-1])
        ),
        "high_52w": _clean(high_52w),
        "low_52w": _clean(low_52w),
        "pct_below_52w_high": pct_from(high_52w),
        "pct_above_52w_low": pct_from(low_52w),
        "annualized_volatility_pct": _clean(annual_vol * 100) if annual_vol else None,
        "volume_trend_pct": _clean(volume_trend),
        "moving_average_cross": cross,
    }


def _fmt(value: Optional[float], suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.2f}{suffix}"


def indicator_summary(ind: dict, currency: str = "") -> str:
    """Render indicators as a compact plain-text table for the LLM to interpret."""
    cur = f" {currency}" if currency else ""
    lines = [
        f"Last close: {_fmt(ind['last_close'])}{cur}",
        f"SMA20 / SMA50 / SMA200: {_fmt(ind['sma20'])} / {_fmt(ind['sma50'])} / {_fmt(ind['sma200'])}",
        f"Price vs SMA50: {_fmt(ind['pct_vs_sma50'], '%')}   "
        f"Price vs SMA200: {_fmt(ind['pct_vs_sma200'], '%')}",
        f"Moving-average state: {ind['moving_average_cross']}",
        f"RSI(14): {_fmt(ind['rsi14'])}",
        f"MACD: {_fmt(ind['macd'])} vs signal {_fmt(ind['macd_signal'])} "
        f"(MACD above signal: {ind['macd_above_signal']})",
        f"52-week high / low: {_fmt(ind['high_52w'])} / {_fmt(ind['low_52w'])}",
        f"Below 52w high: {_fmt(ind['pct_below_52w_high'], '%')}   "
        f"Above 52w low: {_fmt(ind['pct_above_52w_low'], '%')}",
        f"Annualized volatility: {_fmt(ind['annualized_volatility_pct'], '%')}",
        f"20d vs prior 40d volume trend: {_fmt(ind['volume_trend_pct'], '%')}",
    ]
    return "\n".join(lines)


def build_chart(history: pd.DataFrame, max_points: int = 180) -> ChartSeries:
    """Downsample the 1y history into a JSON-safe series for the frontend chart."""
    close = history["Close"].astype(float)
    volume = history["Volume"].astype(float)
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    step = max(1, len(history) // max_points)
    idx = history.index[::step]

    def series(source: pd.Series) -> list[Optional[float]]:
        return [_clean(source.get(ts)) for ts in idx]

    return ChartSeries(
        dates=[ts.strftime("%Y-%m-%d") for ts in idx],
        close=series(close),
        volume=series(volume),
        sma50=series(sma50),
        sma200=series(sma200),
    )


def fetch_market_data(ticker: str) -> dict:
    """Fetch 1y history + profile for a ticker and derive everything downstream.

    Returns a dict with: name, currency, exchange, indicators, indicator_summary,
    and chart. Raises ValueError if the ticker has no usable price history.
    """
    tk = yf.Ticker(ticker)
    history = tk.history(period="1y", auto_adjust=True)
    if history is None or history.empty:
        raise ValueError(f"no price history for '{ticker}'")

    try:
        info = tk.info or {}
    except Exception:
        info = {}

    currency = info.get("currency", "") or ""
    name = info.get("longName") or info.get("shortName") or ticker
    exchange = info.get("exchange", "") or ""

    indicators = compute_indicators(history)
    return {
        "ticker": ticker,
        "name": name,
        "currency": currency,
        "exchange": exchange,
        "indicators": indicators,
        "indicator_summary": indicator_summary(indicators, currency),
        "chart": build_chart(history),
    }
