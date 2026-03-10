import React from 'react';
import { escapeHtml } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

export default function IdeasPanel({ ideas, loading, filterBadge, onOpenModal }) {
    return (
        <>
            <div className="panel-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="panel-title">💡 Ideas & Assessments</span>
                    {filterBadge && (
                        <span className="search-active-badge" dangerouslySetInnerHTML={{ __html: filterBadge }} />
                    )}
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {ideas.length > 0 ? `${ideas.length} TRACKED` : ''}
                </span>
            </div>
            <div className="panel-body">
                {loading ? <LoadingSpinner text="LOADING IDEAS…" /> :
                    ideas.length === 0 ? <EmptyState>No ideas found for this sector</EmptyState> :
                        ideas.map((idea, idx) => {
                            const desc = idea.description || '';
                            const truncDesc = desc.length > 150 ? desc.slice(0, 150) + '…' : desc;
                            const nodeType = idea.node_type || 'Idea';
                            const badgeClass = nodeType === 'Bet' ? 'bet' : 'idea';
                            const parties = (idea.parties || []).filter(p => p);

                            return (
                                <div key={idx} className="idea-card" onClick={() => onOpenModal({ type: 'idea', name: idea.name })}>
                                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                                        <div className="idea-card-name">{idea.name}</div>
                                        <span className={`idea-type-badge ${badgeClass}`}>{nodeType}</span>
                                    </div>
                                    <div className="idea-card-desc">{truncDesc}</div>
                                    {parties.length > 0 && (
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '8px' }}>
                                            {parties.map((p, i) => (
                                                <span key={i} style={{
                                                    background: 'rgba(0, 212, 255, 0.15)', border: '1px solid rgba(0, 212, 255, 0.3)',
                                                    color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)', fontSize: '0.65rem',
                                                    padding: '2px 6px', borderRadius: '4px'
                                                }}>👤 {p}</span>
                                            ))}
                                        </div>
                                    )}
                                    <div className="idea-card-meta">
                                        <span>{idea.date || ''}</span>
                                        <span className="idea-card-check">VIEW & CHECK →</span>
                                    </div>
                                </div>
                            );
                        })
                }
            </div>
        </>
    );
}
