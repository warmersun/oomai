import React, { useState } from 'react';
import { postAdvFilter } from '../api';
import { escapeHtml } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

export default function AdvancementPanel({ advancement, loading, currentEmTech, onPathway }) {
    const [filterQuery, setFilterQuery] = useState('');
    const [filteredLacs, setFilteredLacs] = useState(null);
    const [filtering, setFiltering] = useState(false);
    const [expandedLacs, setExpandedLacs] = useState(new Set());

    const filterAdvancement = async () => {
        if (!filterQuery.trim() || !currentEmTech) return;
        setFiltering(true);
        try {
            const data = await postAdvFilter({ query: filterQuery.trim(), emtech: currentEmTech });
            setFilteredLacs(new Set(data.lacs || []));
        } catch (err) {
            console.error('Filter failed:', err);
        } finally {
            setFiltering(false);
        }
    };

    const clearFilter = () => {
        setFilterQuery('');
        setFilteredLacs(null);
    };

    const toggleLac = (id) => {
        setExpandedLacs(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const displayData = filteredLacs
        ? advancement.map(cap => ({
            ...cap,
            milestones: cap.milestones?.filter(ms =>
                ms.unlocks?.some(u => filteredLacs.has(u.lac_name))
            ) || []
        })).filter(cap => cap.milestones.length > 0)
        : advancement;

    const totalCapabilities = displayData.length;
    const totalMilestones = displayData.reduce((acc, cap) => acc + (cap.milestones?.length || 0), 0);

    return (
        <>
            <div className="panel-header">
                <span className="panel-title">🔬 EmTech Advancement</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                        type="text" placeholder="🔍 Filter use cases..."
                        value={filterQuery}
                        onChange={(e) => setFilterQuery(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') filterAdvancement(); }}
                        style={{
                            padding: '4px 8px', borderRadius: '4px', border: '1px solid var(--border)',
                            background: 'var(--bg-primary)', color: 'var(--text-primary)', fontSize: '0.8rem', width: '200px'
                        }}
                    />
                    <button className="search-bar-btn" onClick={filterAdvancement}
                        style={{ padding: '4px 10px', fontSize: '0.8rem' }} disabled={filtering}>
                        {filtering ? '⏳…' : 'Filter'}
                    </button>
                    {filteredLacs && (
                        <button className="search-bar-btn clear" onClick={clearFilter}
                            style={{ padding: '4px 10px', fontSize: '0.8rem' }}>✕ Clear</button>
                    )}
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: '8px' }}>
                        {totalCapabilities > 0 ? `${totalCapabilities} CAPABILITIES · ${totalMilestones} MILESTONES` : ''}
                    </span>
                </div>
            </div>
            <div className="panel-body">
                {loading ? <LoadingSpinner text="LOADING ADVANCEMENT…" /> :
                    displayData.length === 0 ? <EmptyState>No advancement data for this sector</EmptyState> :
                        displayData.map((cap, ci) => (
                            <div key={ci} className="adv-capability-group">
                                <div className="adv-label" style={{ marginBottom: '4px' }}>Capability</div>
                                <div className="adv-capability-header">
                                    <span className="adv-capability-title">{cap.capability}</span>
                                    {cap.capability_desc && <span className="adv-capability-desc">{cap.capability_desc}</span>}
                                </div>
                                {cap.milestones?.map((ms, mi) => {
                                    const unlocksHtml = ms.unlocks && ms.unlocks.length > 0 ? (
                                        <div className="adv-unlocks-container">
                                            <div className="adv-label">Unlocks Use Cases</div>
                                            {ms.unlocks.map((lac, li) => {
                                                const lacId = `lac-${ci}-${mi}-${li}`;
                                                const isExpanded = expandedLacs.has(lacId);

                                                const productsHtml = lac.products && lac.products.length > 0 ? (
                                                    <div className="adv-product-tree">
                                                        {lac.products.map((ltc, lti) => (
                                                            <div key={lti} className="adv-ltc-group">
                                                                <div className="adv-ltc-name">
                                                                    📦 {ltc.ltc_name}
                                                                    {ltc.ltc_desc && <span className="adv-ltc-desc"> — {ltc.ltc_desc}</span>}
                                                                </div>
                                                                <div className="adv-ptc-list">
                                                                    {(ltc.ptcs || []).map((ptc, pi) => (
                                                                        <div key={pi} className="adv-ptc-card">
                                                                            <div className="adv-ptc-header">
                                                                                <span className="adv-ptc-name">{ptc.name}</span>
                                                                                {ptc.vendor && <span className="adv-ptc-vendor">{ptc.vendor}</span>}
                                                                            </div>
                                                                            {ptc.description && <div className="adv-ptc-desc">{ptc.description}</div>}
                                                                            {ptc.release_date && <div className="adv-ptc-date">{ptc.release_date}</div>}
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                ) : (
                                                    <div className="adv-product-tree">
                                                        <div className="empty-state" style={{ padding: '10px' }}>No products mapped yet</div>
                                                    </div>
                                                );

                                                return (
                                                    <div key={li} className={`adv-lac-item ${isExpanded ? 'expanded' : ''}`}>
                                                        <div className="adv-lac-header" onClick={() => toggleLac(lacId)}>
                                                            <div className="adv-lac-info">
                                                                <span className="adv-lac-name">{lac.lac_name}</span>
                                                                {lac.lac_desc && (
                                                                    <span className="adv-lac-desc">
                                                                        {lac.lac_desc}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                                                                <button className="pathway-btn" onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    onPathway && onPathway({
                                                                        lacName: lac.lac_name,
                                                                        lacDesc: lac.lac_desc || '',
                                                                        milestone: ms.name,
                                                                        capability: cap.capability
                                                                    });
                                                                }}>
                                                                    🛤️ Pathway
                                                                </button>
                                                                <span className="adv-lac-toggle">{isExpanded ? '▲' : '▼'}</span>
                                                            </div>
                                                        </div>
                                                        {productsHtml}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    ) : null;

                                    return (
                                        <div key={mi} className="adv-timeline">
                                            <div className="adv-milestone-card">
                                                <div className="adv-milestone-dot"></div>
                                                <div className="adv-label" style={{ marginBottom: '4px' }}>Reaches Milestone</div>
                                                <div className="adv-milestone-header">
                                                    <div className="adv-milestone-title">{ms.name}</div>
                                                    {ms.date && <div className="adv-milestone-date">{ms.date}</div>}
                                                </div>
                                                {ms.description && <div className="adv-milestone-desc">{ms.description}</div>}
                                                {unlocksHtml}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        ))
                }
            </div>
        </>
    );
}
