# Purpose

## What this system is

The **Multi-Agent Stock Analysis System** answers one question: *"Should I
consider investing in this stock?"* A user types a free-text question about any
US or Indian stock — for example *"Should I invest in Apple for the long
term?"* — and receives a structured **investment-research report** with a
clear rating, the reasoning behind it, the risks against it, and what would
change the conclusion.

Instead of asking one AI model for an opinion, the system splits the job across
**several specialized AI agents arranged in tiers**, mirroring how a real
research desk works: raw data is gathered at the bottom, specialists analyze it
independently in the middle, and a decision-maker at the top weighs their views
into a final call.

```
        [Tier 3: Portfolio Manager]   <-- writes the final report
                    ^
         +----------+----------+
         |                     |
[Tier 2: Technical]   [Tier 2: Sentiment]
      Analyst               Analyst
         ^                     ^
[Tier 1: Stock API]   [Tier 1: News Fetcher]
```

The system is deliberately **not** a trading bot: it never buys or sells
anything, and every report carries a prominent disclaimer that it is
informational only and covers *technicals and news sentiment* — not
fundamentals (earnings, valuation, debt).

## The agents

There are **four AI agents**, each with its own role, its own instructions, and
a strict schema its answer must follow. Orchestration between them is plain
code, not agent-to-agent chatter — which guarantees the data flows exactly as
designed.

### 1. Intake Agent (the front door)
Reads the user's free-text question and extracts the structured facts hidden in
it: which company (or companies) is being asked about, and — only if the user
actually said so — their risk tolerance (conservative / moderate / aggressive)
and investment horizon (short / medium / long). It never guesses ticker
symbols; ambiguity is resolved with the user, not assumed.

### 2. Technical Analyst (Tier 2)
Receives a table of **pre-computed technical indicators** built from one year
of daily price data — moving averages (SMA20/50/200), RSI, MACD, 52-week range
position, volatility, and volume trend. The numbers are calculated
deterministically in Python; the agent's job is purely to *interpret* them,
never to compute. It returns a verdict: **bullish / bearish / neutral**, a
confidence score, evidence tied to specific figures, and honest caveats.

### 3. Sentiment Analyst (Tier 2)
Receives recent **news headlines** for the ticker (cleaned and de-duplicated)
and judges the tone and likely market impact of that news — nothing else. It
returns the same verdict shape as the Technical Analyst. If coverage is thin
(common for Indian listings) it says so and lowers its confidence; if there is
no news at all, this agent is skipped entirely rather than allowed to invent
sentiment.

**A key design rule: the two analysts never see each other's output.** Each
forms an independent opinion, which keeps the final synthesis honest — no
analyst can anchor on the other's conclusion.

### 4. Portfolio Manager (Tier 3)
The senior agent. It receives both analysts' verdicts plus the investor's
profile, and synthesizes them into the final report. When the analysts
disagree — say, bullish technicals but bearish news — it must resolve the
conflict explicitly and reflect that uncertainty in its confidence. It tailors
the recommendation to the stated (or defaulted) risk tolerance and horizon, and
always includes the not-financial-advice disclaimer.

### Supporting cast (not AI)
Tier 1 is ordinary Python code: a **market-data tool** (prices, statistics, and
indicator math via Yahoo Finance) and a **news fetcher**. Ticker resolution —
turning "Reliance" into a concrete stock listing — is also code, backed by a
search API, with a "did you mean…" picker when several stocks match.

## What the final product looks like

The finished product is a **local web application**: one server process serving
both the analysis API and a clean, dark/light-themed single-page site at
`http://localhost:7779`.

**The flow, as the user experiences it:**

1. **Ask** — a single text box: type a question or ticker, click **Analyze**.
2. **(Sometimes) Disambiguate** — if the company name matches several listings
   ("Reliance"), a picker appears: *"Which did you mean?"* with ticker, name,
   and exchange for each candidate. One click continues.
3. **Wait (~10–60 seconds)** — a loading screen narrates the pipeline stages
   as the four agents work ("Understanding your question… analysts working…
   portfolio manager writing the report…").
4. **Read the report** — the page presents, top to bottom:
   - **Verdict card** — a colored rating badge (**Favorable** green /
     **Neutral** amber / **Unfavorable** red) with a confidence percentage, a
     one-sentence bottom line, a note stating the investor profile that was
     assumed, and three columns: **Key reasons**, **Key risks**, and **What
     would change this view**.
   - **Price chart** — an interactive one-year chart with the closing price,
     50- and 200-day moving averages, a volume panel, and a hover crosshair
     with exact values.
   - **Analyst cards** — the Technical and Sentiment analysts side by side,
     each showing its signal pill (bullish/bearish/neutral), confidence,
     summary, evidence list, and caveats — so the user can see *how* the two
     independent opinions fed the final call. If sentiment was unavailable,
     the card says so plainly.
   - **Indicator table** — a collapsible section revealing the exact numbers
     the Technical Analyst was shown, for full auditability.
   - **Disclaimer** — the report is informational, not financial advice, and
     covers technicals + sentiment only.

**Under the hood**, every agent run is traced through AgentOS (viewable on a
dashboard connected to the local server), and the model layer is pluggable: the
same pipeline runs on Groq or Google Gemini free tiers, NVIDIA's free
endpoint, or Anthropic's Claude, selected simply by which API key is present in
the `.env` file.
