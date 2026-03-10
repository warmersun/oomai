import React from 'react';

export default function Modal({ visible, title, onClose, children }) {
    if (!visible) return null;

    return (
        <div
            className={`modal-overlay ${visible ? 'visible' : ''}`}
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        >
            <div className="modal" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                    <h2>{title}</h2>
                    <button className="modal-close" onClick={onClose}>&times;</button>
                </div>
                <div className="modal-body">
                    {children}
                </div>
            </div>
        </div>
    );
}
