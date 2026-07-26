import React, { useMemo, useRef, useState } from "react";

// Categorical palette (validated with dataviz validate_palette.js, light+dark).
// close = blue, SMA50 = orange, SMA200 = violet.
const SERIES = [
  { key: "close", label: "Close", light: "#2a78d6", dark: "#3987e5" },
  { key: "sma50", label: "SMA 50", light: "#eb6834", dark: "#d95926" },
  { key: "sma200", label: "SMA 200", light: "#4a3aa7", dark: "#9085e9" },
];

const W = 820;
const PRICE_H = 300;
const VOL_H = 90;
const PAD = { top: 16, right: 16, bottom: 24, left: 56 };
const GAP = 18; // gap between price panel and volume panel

function niceTicks(min, max, count = 5) {
  if (min === max) return [min];
  const span = max - min;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (span / count) / step;
  const mult = err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
  const nice = mult * step;
  const start = Math.ceil(min / nice) * nice;
  const ticks = [];
  for (let t = start; t <= max + 1e-9; t += nice) ticks.push(t);
  return ticks;
}

export default function PriceChart({ chart, currency }) {
  const ref = useRef(null);
  const [hover, setHover] = useState(null);

  const model = useMemo(() => {
    const n = chart.dates.length;
    const priceVals = [];
    for (const s of SERIES) {
      for (const v of chart[s.key] || []) if (v != null) priceVals.push(v);
    }
    const pMin = Math.min(...priceVals);
    const pMax = Math.max(...priceVals);
    const vMax = Math.max(...chart.volume.filter((v) => v != null), 1);

    const plotW = W - PAD.left - PAD.right;
    const x = (i) => PAD.left + (n <= 1 ? 0 : (i / (n - 1)) * plotW);

    const priceTop = PAD.top;
    const priceBot = PAD.top + PRICE_H;
    const yPrice = (v) =>
      priceBot - ((v - pMin) / (pMax - pMin || 1)) * (priceBot - priceTop);

    const volTop = priceBot + GAP;
    const volBot = volTop + VOL_H;
    const yVol = (v) => volBot - (v / vMax) * (volBot - volTop);

    const line = (key) => {
      const pts = [];
      (chart[key] || []).forEach((v, i) => {
        if (v != null) pts.push(`${x(i)},${yPrice(v)}`);
      });
      return pts.length ? "M" + pts.join(" L") : "";
    };

    return {
      n, x, yPrice, yVol, pMin, pMax, vMax,
      priceTop, priceBot, volTop, volBot, plotW,
      paths: Object.fromEntries(SERIES.map((s) => [s.key, line(s.key)])),
      priceTicks: niceTicks(pMin, pMax, 5),
    };
  }, [chart]);

  const fmt = (v) =>
    v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  const fmtVol = (v) =>
    v == null ? "—" : v >= 1e9 ? (v / 1e9).toFixed(1) + "B"
      : v >= 1e6 ? (v / 1e6).toFixed(1) + "M"
      : v >= 1e3 ? (v / 1e3).toFixed(0) + "K" : String(Math.round(v));

  const onMove = (e) => {
    const rect = ref.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    if (px < PAD.left || px > W - PAD.right) return setHover(null);
    const frac = (px - PAD.left) / model.plotW;
    const i = Math.max(0, Math.min(model.n - 1, Math.round(frac * (model.n - 1))));
    setHover(i);
  };

  const hx = hover != null ? model.x(hover) : null;

  return (
    <figure className="chart">
      <figcaption>1-year price with moving averages, and daily volume</figcaption>
      <div className="legend">
        {SERIES.map((s) => (
          <span key={s.key} className="legend-item">
            <span className="swatch" style={{ background: `var(--${s.key})` }} />
            {s.label}
          </span>
        ))}
      </div>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${PAD.top + PRICE_H + GAP + VOL_H + PAD.bottom}`}
        className="chart-svg"
        role="img"
        aria-label="Price and volume chart"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {/* price gridlines + y labels */}
        {model.priceTicks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left} x2={W - PAD.right}
              y1={model.yPrice(t)} y2={model.yPrice(t)}
              className="grid"
            />
            <text x={PAD.left - 8} y={model.yPrice(t) + 4} className="axis-label" textAnchor="end">
              {fmt(t)}
            </text>
          </g>
        ))}

        {/* volume bars */}
        {chart.volume.map((v, i) =>
          v == null ? null : (
            <line
              key={i} x1={model.x(i)} x2={model.x(i)}
              y1={model.volBot} y2={model.yVol(v)}
              className="vol-bar"
              opacity={hover == null || hover === i ? 0.55 : 0.28}
            />
          )
        )}
        <text x={PAD.left - 8} y={model.volTop + 4} className="axis-label" textAnchor="end">
          {fmtVol(model.vMax)}
        </text>
        <text x={PAD.left - 8} y={model.volBot} className="axis-label muted" textAnchor="end">
          vol
        </text>

        {/* price lines */}
        {SERIES.map((s) => (
          <path
            key={s.key} d={model.paths[s.key]} fill="none"
            stroke={`var(--${s.key})`}
            strokeWidth={s.key === "close" ? 2 : 1.6}
            strokeLinejoin="round" strokeLinecap="round"
            opacity={s.key === "close" ? 1 : 0.9}
          />
        ))}

        {/* x-axis date labels: first / mid / last */}
        {[0, Math.floor(model.n / 2), model.n - 1].map((i) => (
          <text
            key={i} x={model.x(i)} y={model.volBot + 18}
            className="axis-label"
            textAnchor={i === 0 ? "start" : i === model.n - 1 ? "end" : "middle"}
          >
            {chart.dates[i]}
          </text>
        ))}

        {/* hover crosshair + markers */}
        {hx != null && (
          <>
            <line x1={hx} x2={hx} y1={model.priceTop} y2={model.volBot} className="crosshair" />
            {SERIES.map((s) => {
              const v = chart[s.key]?.[hover];
              return v == null ? null : (
                <circle key={s.key} cx={hx} cy={model.yPrice(v)} r={3.5}
                  fill={`var(--${s.key})`} stroke="var(--surface-1)" strokeWidth={1.5} />
              );
            })}
          </>
        )}
      </svg>

      {hover != null && (
        <div className="tooltip">
          <strong>{chart.dates[hover]}</strong>
          {SERIES.map((s) => (
            <div key={s.key} className="tt-row">
              <span className="swatch" style={{ background: `var(--${s.key})` }} />
              {s.label}: {fmt(chart[s.key]?.[hover])} {currency}
            </div>
          ))}
          <div className="tt-row muted">Volume: {fmtVol(chart.volume[hover])}</div>
        </div>
      )}
    </figure>
  );
}
