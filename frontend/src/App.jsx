import React, { useState } from "react";
import PriceChart from "./PriceChart.jsx";

const LOADING_STEPS = [
  "Understanding your question…",
  "Resolving the company…",
  "Fetching prices & computing indicators…",
  "Technical & sentiment analysts working…",
  "Portfolio manager writing the report…",
];

async function postAnalyze(body) {
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Server error (${res.status})`);
  return res.json();
}

function SignalPill({ signal }) {
  return <span className={`pill signal-${signal}`}>{signal}</span>;
}

function RatingBadge({ rating }) {
  return <span className={`badge rating-${rating}`}>{rating}</span>;
}

function Confidence({ value }) {
  return (
    <span className="confidence" title="Confidence">
      {Math.round(value * 100)}% confidence
    </span>
  );
}

function AnalystCard({ title, verdict, unavailable }) {
  if (unavailable) {
    return (
      <div className="card analyst">
        <div className="card-head">
          <h3>{title}</h3>
        </div>
        <p className="muted">
          No news headlines were available for this ticker, so the sentiment
          analyst did not run. The recommendation rests on technicals alone.
        </p>
      </div>
    );
  }
  return (
    <div className="card analyst">
      <div className="card-head">
        <h3>{title}</h3>
        <div className="card-tags">
          <SignalPill signal={verdict.signal} />
          <Confidence value={verdict.confidence} />
        </div>
      </div>
      <p>{verdict.summary}</p>
      {verdict.evidence?.length > 0 && (
        <>
          <h4>Evidence</h4>
          <ul>
            {verdict.evidence.map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        </>
      )}
      {verdict.caveats?.length > 0 && (
        <>
          <h4>Caveats</h4>
          <ul className="muted">
            {verdict.caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}

function Report({ data, onReset }) {
  const { report, technical, sentiment, sentiment_unavailable, profile } = data;
  return (
    <div className="report">
      <div className="report-top">
        <div>
          <h2>{data.company}</h2>
          <span className="ticker">{data.ticker}</span>
        </div>
        <button className="link" onClick={onReset}>← New analysis</button>
      </div>

      <div className="card verdict">
        <div className="verdict-head">
          <RatingBadge rating={report.rating} />
          <Confidence value={report.confidence} />
        </div>
        <p className="verdict-summary">{report.summary}</p>
        <p className="profile-note">
          Assessed for a <strong>{profile.risk_tolerance}</strong> investor over a{" "}
          <strong>{profile.horizon}</strong> horizon
          {profile.tailored ? "" : " (default — you didn't specify one)"}.
        </p>
        <div className="verdict-grid">
          <div>
            <h4>Key reasons</h4>
            <ul>{report.key_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
          <div>
            <h4>Key risks</h4>
            <ul>{report.key_risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
          <div>
            <h4>What would change this view</h4>
            <ul>{report.what_would_change_this.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
        </div>
      </div>

      <PriceChart chart={data.chart} currency={data.currency} />

      <div className="analyst-row">
        <AnalystCard title="Technical Analyst" verdict={technical} />
        <AnalystCard
          title="Sentiment Analyst"
          verdict={sentiment}
          unavailable={sentiment_unavailable}
        />
      </div>

      <details className="indicators">
        <summary>Indicators the technical analyst read</summary>
        <pre>{data.indicator_summary}</pre>
        <p className="muted">Based on {data.headline_count} news headline(s).</p>
      </details>

      <div className="disclaimer">{report.disclaimer}</div>
    </div>
  );
}

function Disambiguation({ message, candidates, onPick }) {
  return (
    <div className="card disambig">
      <p>{message}</p>
      <div className="candidate-list">
        {candidates.map((c) => (
          <button key={c.ticker} className="candidate" onClick={() => onPick(c.ticker)}>
            <strong>{c.ticker}</strong>
            <span>{c.name}</span>
            {c.exchange && <span className="muted">{c.exchange}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

function Loading() {
  const [step, setStep] = useState(0);
  React.useEffect(() => {
    const id = setInterval(() => setStep((s) => Math.min(s + 1, LOADING_STEPS.length - 1)), 4000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="loading">
      <div className="spinner" />
      <p>{LOADING_STEPS[step]}</p>
      <p className="muted small">This runs four Claude agents and can take up to a minute.</p>
    </div>
  );
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState("input"); // input | loading | ambiguous | report | error
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");

  const run = async (body) => {
    setPhase("loading");
    setError("");
    try {
      const data = await postAnalyze(body);
      if (data.status === "complete") {
        setPayload(data);
        setPhase("report");
      } else if (data.status === "ambiguous") {
        setPayload(data);
        setPhase("ambiguous");
      } else {
        setError(data.message || "No result.");
        setPhase("error");
      }
    } catch (e) {
      setError(e.message);
      setPhase("error");
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (question.trim()) run({ question: question.trim() });
  };

  const pick = (ticker) => run({ question: question.trim(), ticker });

  const reset = () => {
    setPhase("input");
    setPayload(null);
    setError("");
  };

  return (
    <div className="app">
      <header>
        <h1>Multi-Agent Stock Analysis</h1>
        <p className="tagline">
          Ask about a stock. A technical analyst and a sentiment analyst each weigh in
          independently, and a portfolio manager writes the final research report.
        </p>
      </header>

      <form className="ask" onSubmit={submit}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Should I invest in Apple for the long term?"
          aria-label="Your question"
        />
        <button type="submit" disabled={phase === "loading" || !question.trim()}>
          Analyze
        </button>
      </form>

      {phase === "loading" && <Loading />}

      {phase === "ambiguous" && (
        <Disambiguation
          message={payload.message}
          candidates={payload.candidates}
          onPick={pick}
        />
      )}

      {phase === "error" && (
        <div className="card error">
          <p>{error}</p>
          <button className="link" onClick={reset}>Try again</button>
        </div>
      )}

      {phase === "report" && payload && <Report data={payload} onReset={reset} />}

      <footer>
        <p className="muted small">
          Informational tool, not financial advice. Analysis covers price technicals and
          news sentiment only — not fundamentals. Every agent run is traced via AgentOS.
        </p>
      </footer>
    </div>
  );
}
