import React, { useState, useRef, useEffect } from 'react';
import { Chart, registerables } from 'chart.js';
import 'chartjs-adapter-date-fns';
import { postTrendAnalyze, postTrendSpot, postTrendSave } from '../api';
import { escapeHtml, EMTECH_COLORS } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

Chart.register(...registerables);

export default function TrendExplorer({
    trends, loading, currentEmTech, filterBadge, onClearFilter, onFollowUp
}) {
    const [spotTopic, setSpotTopic] = useState('');
    const [spotting, setSpotting] = useState(false);
    const [activeIdx, setActiveIdx] = useState(null);
    const [detailView, setDetailView] = useState(null); // 'detail' | 'chart' | 'spotted' | null
    const [detailData, setDetailData] = useState(null);
    const [chartData, setChartData] = useState(null);
    const [chartLoading, setChartLoading] = useState(false);
    const [doublingInfo, setDoublingInfo] = useState('');
    const chartRef = useRef(null);
    const chartInstance = useRef(null);

    // Deduplicate trends
    const seen = new Set();
    const uniqueTrends = (trends || []).filter(t => {
        if (seen.has(t.name)) return false;
        seen.add(t.name);
        return true;
    });

    useEffect(() => {
        return () => { if (chartInstance.current) chartInstance.current.destroy(); };
    }, []);

    // Reset on EmTech change
    useEffect(() => {
        setActiveIdx(null);
        setDetailView(null);
        setDetailData(null);
        setChartData(null);
        setDoublingInfo('');
        setSpotTopic('');
        if (chartInstance.current) { chartInstance.current.destroy(); chartInstance.current = null; }
    }, [currentEmTech]);

    const openDetail = (idx) => {
        setActiveIdx(idx);
        setDetailView('detail');
        setDetailData(uniqueTrends[idx]);
        setChartData(null);
        setDoublingInfo('');
        if (chartInstance.current) { chartInstance.current.destroy(); chartInstance.current = null; }
    };

    const visualizeGrowth = async (idx) => {
        const trend = uniqueTrends[idx];
        if (!trend) return;
        setChartLoading(true);
        setDetailView('chart');
        setDoublingInfo('');
        try {
            const data = await postTrendAnalyze({ trend_name: trend.name, emtech: currentEmTech });
            if (data.detail) {
                setDetailView('detail');
                setDetailData({ ...trend, _error: data.detail });
                return;
            }
            // Store for follow-up
            window._lastTrendAnalysis = data;
            setChartData(data);
            setDetailView('chart');
        } catch (err) {
            setDetailView('detail');
            setDetailData({ ...trend, _error: err.message });
        } finally {
            setChartLoading(false);
        }
    };

    useEffect(() => {
        if (detailView !== 'chart' || !chartData || !chartRef.current) return;
        renderChart(chartData);
    }, [detailView, chartData]);

    const renderChart = (data) => {
        if (!chartRef.current) return;
        if (chartInstance.current) chartInstance.current.destroy();

        const { milestones, doubling } = data;
        const mpd = doubling?.months_per_doubling || 12;
        const color = EMTECH_COLORS[currentEmTech] || '#00d4ff';
        const confClass = doubling?.confidence === 'low' ? 'low-confidence' : '';

        setDoublingInfo(`<span class="doubling-badge ${confClass}" title="${escapeHtml(doubling?.reasoning || '')}">⚡ ${mpd} mo/doubling · ${escapeHtml(doubling?.metric || 'capability')}</span>`);

        const dated = milestones.filter(m => m.date).sort((a, b) => new Date(a.date) - new Date(b.date));
        if (dated.length === 0) {
            setDetailView('detail');
            setDetailData({ _error: "No dated milestones for this trend's capabilities" });
            return;
        }
        const msPoints = dated.map((m, i) => ({ x: new Date(m.date), y: i + 1, name: m.name }));
        const startDate = msPoints[0].x;
        const endDate = new Date(Math.max(msPoints[msPoints.length - 1].x.getTime(), Date.now()));
        const futureDate = new Date(endDate);
        futureDate.setMonth(futureDate.getMonth() + 18);
        const trendLinePoints = [];
        const totalMonths = (futureDate - startDate) / (1000 * 60 * 60 * 24 * 30.44);
        const steps = Math.min(80, Math.max(20, Math.ceil(totalMonths)));
        for (let i = 0; i <= steps; i++) {
            const t = (i / steps) * totalMonths;
            const date = new Date(startDate.getTime() + t * 30.44 * 24 * 60 * 60 * 1000);
            trendLinePoints.push({ x: date, y: Math.pow(2, t / mpd) });
        }
        const maxY = Math.max(msPoints[msPoints.length - 1].y, trendLinePoints[trendLinePoints.length - 1].y) * 1.2;

        const datasets = [
            {
                label: '🏁 Milestones', data: msPoints, borderColor: 'transparent',
                backgroundColor: color + 'cc', pointBackgroundColor: color,
                pointBorderColor: '#fff', pointBorderWidth: 2, pointRadius: 7,
                pointHoverRadius: 11, pointHitRadius: 14, showLine: false, order: 1,
            },
            {
                label: `📈 Trend (${mpd}mo doubling)`, data: trendLinePoints,
                borderColor: '#00ff8866', backgroundColor: 'rgba(0,255,136,0.03)',
                borderWidth: 2, borderDash: [8, 4], pointRadius: 0, pointHitRadius: 0,
                fill: true, showLine: true, tension: 0, order: 2,
            },
        ];

        const ctx = chartRef.current.getContext('2d');
        chartInstance.current = new Chart(ctx, {
            type: 'scatter',
            data: { datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: true },
                plugins: {
                    legend: { position: 'bottom', labels: { color: '#7a8ca0', font: { family: "'JetBrains Mono', monospace", size: 10 }, boxWidth: 12, padding: 16 } },
                    tooltip: {
                        backgroundColor: 'rgba(6,6,12,0.95)', titleColor: '#00d4ff', bodyColor: '#e0e6ed',
                        borderColor: 'rgba(0,212,255,0.3)', borderWidth: 1, padding: 12, cornerRadius: 8,
                        callbacks: {
                            title: (items) => datasets[items[0].datasetIndex].data[items[0].dataIndex]?.name || '',
                            label: (item) => new Date(item.parsed.x).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }),
                        },
                        filter: (item) => datasets[item.datasetIndex].label === '🏁 Milestones',
                    },
                },
                scales: {
                    x: { type: 'time', time: { unit: 'month', displayFormats: { month: 'MMM yyyy' } }, grid: { color: 'rgba(100,220,255,0.04)' }, ticks: { color: '#4a5568', font: { family: "'JetBrains Mono', monospace", size: 9 }, maxTicksLimit: 12 } },
                    y: { type: 'logarithmic', min: 0.5, max: maxY, grid: { color: 'rgba(100,220,255,0.04)' }, ticks: { color: '#4a5568', font: { family: "'JetBrains Mono', monospace", size: 9 }, callback: v => v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v >= 1 ? Math.round(v) + '' : '' } },
                },
            },
        });
    };

    const spotTrend = async () => {
        if (!spotTopic.trim() || !currentEmTech) return;
        setSpotting(true);
        setDetailView('chart');
        setChartLoading(true);
        setDoublingInfo('');
        if (chartInstance.current) { chartInstance.current.destroy(); chartInstance.current = null; }
        try {
            const data = await postTrendSpot({ topic: spotTopic.trim(), emtech: currentEmTech });
            if (data.detail) {
                setDetailView('detail');
                setDetailData({ _error: data.detail });
                return;
            }
            setDetailView('spotted');
            setDetailData({ spotted: data.spotted, emtech: data.emtech });
            setChartData(null);
            window._spottedTrend = { trend_name: data.spotted.trend_name, description: data.spotted.description, capabilities: data.spotted.capabilities, emtech: data.emtech };
        } catch (err) {
            setDetailView('detail');
            setDetailData({ _error: err.message });
        } finally {
            setSpotting(false);
            setChartLoading(false);
        }
    };

    const saveTrend = async () => {
        const data = window._spottedTrend;
        if (!data) return;
        try {
            const result = await postTrendSave(data);
            if (result.status === 'saved') {
                // Trigger refresh in parent would be needed
            }
        } catch (err) {
            console.error('Save error:', err);
        }
    };

    const renderChartArea = () => {
        if (chartLoading) return <LoadingSpinner text="ANALYZING TREND…<br>AI is calculating growth rate" />;

        if (detailView === 'chart') {
            return (
                <div className="chart-container" style={{ height: '380px' }}>
                    <canvas ref={chartRef} />
                </div>
            );
        }

        if (detailView === 'spotted' && detailData?.spotted) {
            const s = detailData.spotted;
            return (
                <div className="spotted-result">
                    <div className="spotted-label">🔭 AI-SPOTTED TREND</div>
                    <div className="spotted-name">{s.trend_name || 'Unnamed Trend'}</div>
                    <div className="spotted-desc">{s.description || ''}</div>
                    {s.months_per_doubling && (
                        <div style={{ marginBottom: '10px' }}>
                            <span className="doubling-badge">⚡ {s.months_per_doubling} mo/doubling · {s.metric || ''}</span>
                        </div>
                    )}
                    {s.prediction && (
                        <div style={{ fontSize: '0.74rem', color: 'var(--accent-amber)', marginBottom: '10px' }}>🔮 {s.prediction}</div>
                    )}
                    {s.evidence?.length > 0 && (
                        <ul className="spotted-evidence">{s.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
                    )}
                    <div className="trend-detail-actions">
                        <button className="save-trend-btn" onClick={saveTrend}>💾 Save to Knowledge Graph</button>
                        <button className="follow-up-btn" onClick={() => onFollowUp?.({
                            type: 'spotted trend', title: s.trend_name,
                            content: `Trend: ${s.trend_name}\nDescription: ${s.description}\nEvidence: ${(s.evidence || []).join(', ')}`
                        })}>💬 Follow up in AI Chat</button>
                    </div>
                </div>
            );
        }

        if (detailView === 'detail' && detailData) {
            if (detailData._error) return <EmptyState>⚠️ {detailData._error}</EmptyState>;
            const trend = detailData;
            const parties = (trend.parties || []).filter(p => p);
            return (
                <div className="trend-detail-card">
                    <div className="trend-detail-name">📈 {trend.name}</div>
                    <div className="trend-detail-desc">{trend.description || 'No description available'}</div>
                    <div className="trend-detail-meta" style={{ flexWrap: 'wrap', gap: '8px' }}>
                        {trend.capability && <span>🎯 Capability: {trend.capability}</span>}
                        {trend.observed_date && <span>📅 Observed: {trend.observed_date}</span>}
                        {parties.length > 0 && (
                            <span style={{ background: 'rgba(0,212,255,0.15)', color: 'var(--accent-cyan)', padding: '4px 8px', borderRadius: '4px', border: '1px solid rgba(0,212,255,0.3)' }}>
                                👤 Spotted by: {parties.join(', ')}
                            </span>
                        )}
                    </div>
                    <div className="trend-detail-actions">
                        <button className="trend-action-btn primary" onClick={() => visualizeGrowth(activeIdx)}>📈 Visualize Growth</button>
                    </div>
                </div>
            );
        }

        return <EmptyState>📈 Select a trend or spot a new one</EmptyState>;
    };

    return (
        <>
            <div className="panel-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="panel-title">
                        {currentEmTech ? `📊 ${currentEmTech.toUpperCase()} — TREND EXPLORER` : '📊 Trend Explorer'}
                    </span>
                    {filterBadge && (
                        <span className="search-active-badge">
                            <span dangerouslySetInnerHTML={{ __html: filterBadge }} />
                            {onClearFilter && (
                                <button
                                    onClick={(e) => { e.stopPropagation(); onClearFilter(); }}
                                    style={{
                                        background: 'none', border: 'none', color: 'inherit',
                                        cursor: 'pointer', marginLeft: '6px', padding: '0 2px',
                                        fontSize: '0.8rem', opacity: 0.8
                                    }}
                                    title="Clear filter"
                                >✕</button>
                            )}
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {doublingInfo && <span dangerouslySetInnerHTML={{ __html: doublingInfo }} />}
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)' }}>LOG SCALE</span>
                </div>
            </div>
            <div className="trend-explorer" style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {/* Left: trend list */}
                <div className="trend-list-area">
                    <div className="trend-spot-input">
                        <input type="text" placeholder="Spot a trend…" value={spotTopic}
                            onChange={(e) => setSpotTopic(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') spotTrend(); }}
                        />
                        <button className="trend-spot-btn" disabled={spotting} onClick={spotTrend}>
                            {spotting ? '⏳…' : '🔭 Spot'}
                        </button>
                    </div>
                    <div className="trend-count">{uniqueTrends.length} TRENDS</div>
                    <div className="trend-scroll">
                        {loading ? <LoadingSpinner text="LOADING…" /> :
                            uniqueTrends.length === 0 ? (
                                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                                    No trends observed yet.<br />Use the input above to spot one!
                                </div>
                            ) : uniqueTrends.map((t, idx) => {
                                const parties = (t.parties || []).filter(p => p);
                                return (
                                    <div key={idx} className={`trend-list-item ${activeIdx === idx ? 'active' : ''}`}
                                        onClick={() => openDetail(idx)}>
                                        <span className="trend-list-icon">📈</span>
                                        <div style={{ minWidth: 0, flex: 1 }}>
                                            <span className="trend-list-name">{t.name}</span>
                                            {parties.length > 0 && (
                                                <div style={{ marginTop: '4px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                                    {parties.map((p, i) => (
                                                        <span key={i} style={{
                                                            background: 'rgba(0,212,255,0.1)', color: 'var(--accent-cyan)',
                                                            fontFamily: 'var(--font-mono)', fontSize: '0.65rem', padding: '2px 6px',
                                                            borderRadius: '4px', border: '1px solid rgba(0,212,255,0.2)',
                                                        }}>👤 {p}</span>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                    </div>
                </div>
                {/* Right: chart or detail */}
                <div className="chart-main-area" style={{ flex: 1, minHeight: 0 }}>
                    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                        {renderChartArea()}
                    </div>
                </div>
            </div>
        </>
    );
}
