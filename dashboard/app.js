import React, { useEffect, useMemo, useRef, useState } from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
};

function App() {
  const [emtechs, setEmtechs] = useState([]);
  const [active, setActive] = useState("");
  const [trends, setTrends] = useState([]);
  const [bets, setBets] = useState([]);
  const [ideas, setIdeas] = useState([]);
  const [advancement, setAdvancement] = useState([]);
  const [convergences, setConvergences] = useState([]);
  const [topic, setTopic] = useState("");
  const [intel, setIntel] = useState("");

  useEffect(() => {
    api("/api/emtechs").then((data) => {
      setEmtechs(data);
      if (data.length) setActive(data[0].name);
    });
  }, []);

  useEffect(() => {
    if (!active) return;
    Promise.all([
      api(`/api/emtech/${encodeURIComponent(active)}/trends`),
      api(`/api/emtech/${encodeURIComponent(active)}/bets`),
      api(`/api/emtech/${encodeURIComponent(active)}/ideas`),
      api(`/api/emtech/${encodeURIComponent(active)}/advancement`),
      api(`/api/emtech/${encodeURIComponent(active)}/convergences`),
    ]).then(([trendData, betData, ideaData, advancementData, convergenceData]) => {
      setTrends(trendData);
      setBets(betData);
      setIdeas(ideaData);
      setAdvancement(advancementData);
      setConvergences(convergenceData);
    });
  }, [active]);

  const trendPoints = useMemo(
    () =>
      trends
        .filter((t) => t.observed_date)
        .map((t) => ({ x: t.observed_date, y: t.name.length })),
    [trends]
  );

  const chartRef = useRef(null);
  useEffect(() => {
    if (!chartRef.current || !window.Chart) return;
    const chart = new window.Chart(chartRef.current, {
      type: "line",
      data: {
        datasets: [
          {
            label: "Trend Signals",
            data: trendPoints,
            borderColor: "#00d4ff",
            backgroundColor: "rgba(0,212,255,0.2)",
            tension: 0.3,
          },
        ],
      },
      options: {
        parsing: false,
        scales: {
          x: { type: "time" },
          y: { title: { display: true, text: "Signal Strength" } },
        },
        plugins: { legend: { display: false } },
        maintainAspectRatio: false,
      },
    });
    return () => chart.destroy();
  }, [trendPoints]);

  const runNewsScan = async () => {
    if (!topic) return;
    const result = await api("/api/news", {
      method: "POST",
      body: JSON.stringify({ topic }),
    });
    setIntel(result.analysis || result.summary || JSON.stringify(result));
  };

  return html`
    <div>
      <header className="header">
        <h1 className="header-title">Monitoring the Situation</h1>
        <div className="header-status"><span className="status-dot"></span>LIVE DATA LINKED</div>
      </header>

      <div className="tab-bar-wrapper">
        <nav className="tab-bar">
          ${emtechs.map(
            (em) => html`<button className=${`tab ${active === em.name ? "active" : ""}`} onClick=${() => setActive(em.name)}>
              <span className="tab-icon">${em.icon || "🔬"}</span>${em.name}
            </button>`
          )}
        </nav>
      </div>

      <main className="dashboard" style=${{ padding: "0 32px 32px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
        <section className="panel chart-panel">
          <div className="panel-header"><span className="panel-title">📊 Trend Explorer</span></div>
          <div className="panel-body" style=${{ height: "320px" }}>
            <canvas ref=${chartRef}></canvas>
          </div>
          <div className="trend-scroll" style=${{ padding: "12px" }}>
            ${trends.slice(0, 8).map((t) => html`<div className="trend-item">${t.name}</div>`)}
          </div>
        </section>

        <section className="panel news-panel">
          <div className="panel-header">
            <span className="panel-title">📡 Latest Intel</span>
            <div style=${{ display: "flex", gap: "8px" }}>
              <input className="intel-topic-input" value=${topic} onInput=${(e) => setTopic(e.target.value)} placeholder="Enter news topic" />
              <button className="scan-btn" onClick=${runNewsScan}>Scan</button>
            </div>
          </div>
          <div className="panel-body"><pre style=${{ whiteSpace: "pre-wrap" }}>${intel || "Run a scan to receive synthesized intel."}</pre></div>
        </section>

        <section className="panel bets-panel">
          <div className="panel-header"><span className="panel-title">🎯 Active Bets</span></div>
          <div className="panel-body">${bets.slice(0, 6).map((b) => html`<div className="bet-card">${b.name}</div>`)}</div>
        </section>

        <section className="panel ideas-panel">
          <div className="panel-header"><span className="panel-title">💡 Ideas & Assessments</span></div>
          <div className="panel-body">${ideas.slice(0, 6).map((i) => html`<div className="idea-card">${i.name}</div>`)}</div>
        </section>

        <section className="panel advancement-panel">
          <div className="panel-header"><span className="panel-title">🔬 EmTech Advancement</span></div>
          <div className="panel-body">${advancement.slice(0, 8).map((a) => html`<div className="advancement-item">${a.capability || a.name}</div>`)}</div>
        </section>

        <section className="panel convergences-panel">
          <div className="panel-header"><span className="panel-title">🔗 Convergences</span></div>
          <div className="panel-body">${convergences.slice(0, 8).map((c) => html`<div className="convergence-item">${c.name || c.capability}</div>`)}</div>
        </section>
      </main>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
