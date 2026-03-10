import React from 'react';
import { escapeHtml } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

export default function BetsPanel({ bets, loading, onOpenModal }) {
    const getStatus = (b) => {
        const hasValidation = b.validations?.some(v => v.milestone);
        const hasInvalidation = b.invalidations?.some(v => v.source);
        if (b.result) {
            return b.result.toLowerCase().includes('invalid')
                ? { label: '❌ INVALIDATED', cls: 'invalidated' }
                : { label: '✅ VALIDATED', cls: 'validated' };
        }
        if (hasValidation) return { label: '✅ SIGNAL VALIDATED', cls: 'validated' };
        if (hasInvalidation) return { label: '❌ SIGNAL AGAINST', cls: 'invalidated' };
        return { label: '⏳ PENDING', cls: 'pending' };
    };

    return (
        <>
            <div className="panel-header">
                <span className="panel-title">🎯 Active Bets</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {bets.length > 0 ? `${bets.length} TRACKED` : ''}
                </span>
            </div>
            <div className="panel-body">
                {loading ? <LoadingSpinner text="LOADING BETS…" /> :
                    bets.length === 0 ? <EmptyState>No active bets for this sector</EmptyState> :
                        bets.map((b, idx) => {
                            const st = getStatus(b);
                            return (
                                <div key={idx} className="bet-card" onClick={() => onOpenModal({ type: 'bet', data: b, idx })}>
                                    <span className={`bet-status ${st.cls}`}>{st.label}</span>
                                    <div className="bet-name">{b.name}</div>
                                    <div className="bet-desc">{b.description || ''}</div>
                                    {b.placed_date && <div className="bet-date">Placed: {b.placed_date}</div>}
                                </div>
                            );
                        })
                }
            </div>
        </>
    );
}
