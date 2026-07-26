"""Tier 1: per-ticker news headlines from Yahoo Finance (via yfinance).

Yahoo's news payload schema has changed over time, so parsing is defensive:
it handles both the newer nested ``content`` shape and the older flat shape.
Coverage for non-US (e.g. NSE ``.NS``) tickers is typically thinner than for
US names -- the Sentiment Analyst is told when the sample is small.
"""

from __future__ import annotations

from typing import Optional

import yfinance as yf


def _extract(article: dict) -> Optional[dict]:
    """Normalize one Yahoo news item to {title, publisher, date, summary}."""
    content = article.get("content") if isinstance(article.get("content"), dict) else None

    if content:
        title = content.get("title")
        summary = content.get("summary") or content.get("description") or ""
        date = content.get("pubDate") or content.get("displayTime") or ""
        provider = content.get("provider") or {}
        publisher = provider.get("displayName", "") if isinstance(provider, dict) else ""
    else:
        title = article.get("title")
        summary = article.get("summary", "")
        date = article.get("providerPublishTime") or ""
        publisher = article.get("publisher", "")

    if not title:
        return None
    return {
        "title": title.strip(),
        "publisher": (publisher or "").strip(),
        "date": str(date),
        "summary": (summary or "").strip()[:400],
    }


def fetch_news(ticker: str, count: int = 10) -> list[dict]:
    """Fetch and clean recent headlines for a ticker. Returns [] on failure."""
    try:
        raw = yf.Ticker(ticker).get_news(count=count)
    except Exception:
        return []

    seen: set[str] = set()
    cleaned: list[dict] = []
    for article in raw or []:
        item = _extract(article)
        if item is None:
            continue
        key = item["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def headlines_text(news: list[dict]) -> str:
    """Render cleaned headlines as a numbered block for the Sentiment Analyst."""
    if not news:
        return "(no headlines available)"
    lines = []
    for i, item in enumerate(news, 1):
        meta = " / ".join(part for part in (item["publisher"], item["date"]) if part)
        header = f"{i}. {item['title']}"
        if meta:
            header += f"  [{meta}]"
        lines.append(header)
        if item["summary"]:
            lines.append(f"   {item['summary']}")
    return "\n".join(lines)
