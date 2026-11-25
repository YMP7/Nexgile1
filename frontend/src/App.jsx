import React, { useEffect, useState } from "react";

const INITIATIVES = ["onboarding", "europe_price", "referral"];
const REC_COLOR = { keep: "#1a7f37", change: "#b08800", stop: "#cf222e" };
const fmt = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

// Horizontal bars from zero, with a whisker for the 95% range. Hover/focus a row for detail.
function BridgeChart({ rows, hover, setHover }) {
  const W = 900, left = 360, right = 30, rowH = 60, top = 20;
  const lo = Math.min(0, ...rows.map((r) => r.range[0])) - 0.5;
  const hi = Math.max(0, ...rows.map((r) => r.range[1])) + 0.5;
  const x = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
  const H = top + rows.length * rowH + 10;
  return (
    <svg width={W} height={H} role="img" aria-label="Revenue bridge, percentage points of Q2 revenue">
      <line x1={x(0)} x2={x(0)} y1={top - 10} y2={H - 5} stroke="#555" />
      {rows.map((r, i) => {
        const y = top + i * rowH;
        const v = r.pct_points;
        const color = v < 0 ? "#cf222e" : "#1a7f37";
        return (
          <g
            key={r.cause}
            tabIndex={0}
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            style={{ cursor: "pointer", outline: "none" }}
          >
            <title>{`${r.cause}: ${fmt(v)}pp, range ${fmt(r.range[0])} to ${fmt(r.range[1])}`}</title>
            <rect x={0} y={y - 6} width={W} height={rowH - 4} fill={hover === i ? "#eef" : "transparent"} />
            <text x={left - 10} y={y + 14} textAnchor="end" fontSize="13">{r.cause}</text>
            <rect x={x(Math.min(0, v))} y={y} width={Math.abs(x(v) - x(0))} height={20} fill={color} />
            <line x1={x(r.range[0])} x2={x(r.range[1])} y1={y + 10} y2={y + 10} stroke="#000" />
            <line x1={x(r.range[0])} x2={x(r.range[0])} y1={y + 4} y2={y + 16} stroke="#000" />
            <line x1={x(r.range[1])} x2={x(r.range[1])} y1={y + 4} y2={y + 16} stroke="#000" />
            <text x={x(0)} y={y + 40} fontSize="12" textAnchor="middle" fill="#333" stroke="#fff" strokeWidth="4" paintOrder="stroke">
              {`${fmt(v)}pp  [${fmt(r.range[0])}, ${fmt(r.range[1])}]`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function InitiativeCard({ d }) {
  const [lo, hi] = d.effect.range;
  return (
    <div style={{ border: "1px solid #ccc", padding: 12, width: 300 }}>
      <h3 style={{ margin: "0 0 6px" }}>{d.name}</h3>
      <div>
        <span style={{ background: REC_COLOR[d.recommendation], color: "#fff", padding: "2px 8px", fontWeight: "bold" }}>
          {d.recommendation.toUpperCase()}
        </span>{" "}
        confidence: <b>{d.confidence}</b>
      </div>
      <p style={{ margin: "8px 0" }}>
        {d.effect.metric}: <b>{fmt(d.effect.value)}</b> (95% range {fmt(lo)} to {fmt(hi)})
      </p>
      <details>
        <summary>evidence</summary>
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 11 }}>{JSON.stringify(d.evidence, null, 2)}</pre>
      </details>
      <details>
        <summary>query</summary>
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 11 }}>{d.evidence_query}</pre>
      </details>
      <small>{d.confidence_rule}</small>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    Promise.all([
      get("/api/revenue-bridge"),
      get("/api/summary"),
      ...INITIATIVES.map((n) => get(`/api/initiative/${n}`)),
    ])
      .then(([bridge, summary, ...inits]) => setData({ bridge, summary, inits }))
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p style={{ color: "#cf222e" }}>Failed to load: {error}</p>;
  if (!data) return <p>Loading...</p>;
  const { bridge, summary, inits } = data;

  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: 980, margin: "20px auto", padding: "0 12px" }}>
      <h1>Q3 vs Q2 revenue: {summary.revenue_change_pct.toFixed(2)}%</h1>
      <p>
        Q2 ${summary.q2_net_revenue.toLocaleString()} → Q3 ${summary.q3_net_revenue.toLocaleString()} · signups{" "}
        {summary.signups.q2} → {summary.signups.q3} ({fmt(summary.signups.change_pct)}%)
      </p>

      <h2>CEO memo</h2>
      <div style={{ whiteSpace: "pre-wrap", background: "#f6f8fa", padding: 12 }}>{summary.memo}</div>

      <h2>Revenue bridge (percentage points of Q2 revenue)</h2>
      <BridgeChart rows={bridge} hover={hover} setHover={setHover} />
      {hover !== null && (
        <div style={{ border: "1px solid #ccc", padding: 8, margin: "8px 0" }}>
          <b>{bridge[hover].cause}</b>: {fmt(bridge[hover].pct_points)}pp, range {fmt(bridge[hover].range[0])} to{" "}
          {fmt(bridge[hover].range[1])}
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 11 }}>{bridge[hover].evidence_query}</pre>
        </div>
      )}
      <p>
        Sum of bars: {fmt(bridge.reduce((s, b) => s + b.pct_points, 0))}pp (matches total {fmt(summary.revenue_change_pct)}%).
      </p>

      <h2>Initiatives</h2>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {inits.map((d) => (
          <InitiativeCard key={d.name} d={d} />
        ))}
      </div>
    </main>
  );
}
