import React from 'react';
import { escapeHtml } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

export default function ConvergencesPanel({ convergences, loading, filterBadge, onOpenModal }) {
    return (
        <>
            <div className="panel-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="panel-title">🔗 Convergences</span>
                    {filterBadge && (
                        <span className="search-active-badge" dangerouslySetInnerHTML={{ __html: filterBadge }} />
                    )}
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {convergences.length > 0 ? `${convergences.length}` : ''}
                </span>
            </div>
            <div className="panel-body">
                {loading ? <LoadingSpinner text="LOADING CONVERGENCES…" /> :
                    convergences.length === 0 ? <EmptyState>No convergences found for this EmTech</EmptyState> :
                        <div className="conv-list">
                            {convergences.map((c, idx) => {
                                const isAccelerates = c.direction === 'ACCELERATES';
                                const dirClass = isAccelerates ? 'accelerates' : 'accelerated-by';
                                const dirLabel = isAccelerates ? '→ accelerates' : '← accelerated by';
                                const otherEmtechs = (c.other_emtechs || []).filter(e => e);

                                return (
                                    <div key={idx} className="conv-card" onClick={() => onOpenModal && onOpenModal({ type: 'convergence', data: c, idx })}>
                                        <div className="conv-card-name">🔗 {c.name}</div>
                                        {c.description && <div className="conv-card-desc">{c.description}</div>}
                                        <div className="conv-card-meta">
                                            <span className={`conv-direction ${dirClass}`}>{dirLabel}</span>
                                            {otherEmtechs.map((e, i) => (
                                                <span key={i} className="conv-emtech-badge">{e}</span>
                                            ))}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                }
            </div>
        </>
    );
}
