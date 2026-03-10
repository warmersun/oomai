import React from 'react';

export function LoadingSpinner({ text = 'LOADING…' }) {
    return (
        <div className="loading-container">
            <div className="loading-spinner"></div>
            <div className="loading-text" dangerouslySetInnerHTML={{ __html: text }} />
        </div>
    );
}

export function EmptyState({ children }) {
    return <div className="empty-state">{children}</div>;
}
