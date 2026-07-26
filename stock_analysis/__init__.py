"""Multi-agent stock analysis system.

A three-tier pipeline that turns a free-text question about a stock into an
investment-research report:

    Tier 1 (tools)     market_data + news  -- pure Python, no LLM
    Tier 2 (analysts)  Technical + Sentiment analysts (run independently)
    Tier 3 (manager)   Portfolio Manager synthesizes a final report

Orchestration lives in ``stock_service.py`` at the repo root.
"""
