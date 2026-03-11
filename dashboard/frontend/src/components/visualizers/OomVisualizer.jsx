import React, { useState, useEffect } from "react";

export default function OomVisualizer({ monthsPerDoubling = 12 }) {
  const TARGETS = [1, 10, 100, 1000];

  const [doublings, setDoublings] = useState(0);
  const [target, setTarget] = useState(100);
  const [projection, setProjection] = useState("");

  const need = Math.ceil(Math.log2(target));
  const totalMonths = need * monthsPerDoubling;
  const years = Math.floor(totalMonths / 12);
  const months = totalMonths % 12;

  useEffect(() => {
    const future = new Date();
    future.setMonth(future.getMonth() + doublings * monthsPerDoubling);
    setProjection(future.toLocaleDateString(undefined, { month: "short", year: "numeric" }));
  }, [doublings, monthsPerDoubling]);

  const filled = Math.min(1024, 2 ** doublings);

  const btnStyle = (active) => ({
    padding: "4px 12px",
    background: active ? "var(--accent-red)" : "transparent",
    color: active ? "white" : "var(--text)",
    border: `1px solid ${active ? "var(--accent-red)" : "var(--border)"}`,
    borderRadius: "4px",
    cursor: "pointer",
    fontSize: "0.8rem",
    fontWeight: "bold"
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "16px", margin: "16px 0", padding: "16px", border: "1px solid var(--border)", borderRadius: "8px", background: "var(--bg-secondary)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <button onClick={() => setDoublings(d => Math.max(0, d - 1))} style={btnStyle(false)}>‹</button>
        <input
          type="range"
          min={0}
          max={10}
          value={doublings}
          onChange={e => setDoublings(+e.target.value)}
          style={{ width: "200px" }}
        />
        <button onClick={() => setDoublings(d => Math.min(10, d + 1))} style={btnStyle(false)}>›</button>
      </div>

      <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
        {doublings} / 10 doublings → <strong style={{color:"var(--text)"}}>{doublings * monthsPerDoubling}</strong> mo ⇒ <strong style={{color:"var(--accent-cyan)"}}>{projection}</strong>
      </div>

      <div style={{ textAlign: "center", fontSize: "0.9rem" }}>
        Goal: <strong style={{color:"var(--accent-purple)"}}>{target}×</strong> ⇒ <strong>{need} doublings</strong><br />
        ETA @ <strong style={{color:"var(--accent-cyan)"}}>{monthsPerDoubling} mo/doubling</strong> ≈ <strong>{years} y {months} m</strong>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(32, 1fr)",
          gap: "2px",
          width: "100%",
          maxWidth: "400px",
          background: "rgba(0,0,0,0.5)",
          padding: "8px",
          borderRadius: "8px",
          border: "1px solid var(--border)"
        }}
      >
        {Array.from({ length: 1024 }).map((_, i) => (
          <div
            key={i}
            style={{
              backgroundColor: i < filled ? "var(--accent-red)" : i < target ? "var(--accent-yellow)" : "rgba(255,255,255,0.1)",
              width: "100%",
              paddingTop: "100%",
              borderRadius: "1px"
            }}
          />
        ))}
      </div>

      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", justifyContent: "center" }}>
        {TARGETS.map(f => (
          <button
            key={f}
            style={btnStyle(f === target)}
            onClick={() => setTarget(f)}
          >
            {f}×
          </button>
        ))}
      </div>
    </div>
  );
}
