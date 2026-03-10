import React from 'react';

export default function Header({ statusText, statusOk = true }) {
    return (
        <header className="header">
            <h1 className="header-title">Monitoring the Situation</h1>
            <div className="header-status">
                <span
                    className="status-dot"
                    style={statusOk ? {} : { background: '#ff4757', boxShadow: '0 0 8px #ff4757' }}
                />
                <span>{statusText}</span>
            </div>
        </header>
    );
}
