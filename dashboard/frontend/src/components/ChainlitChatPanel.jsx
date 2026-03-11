import React, { useEffect, useMemo, useRef, useState } from 'react';

function formatFollowUpContext(followUpContext) {
    if (!followUpContext) return '';
    return `I'm following up on a ${followUpContext.type} about "${followUpContext.title}".

Here is the context:

${followUpContext.content}

My question/request is:`;
}

function parseServerPayload(raw) {
    if (typeof raw === 'object' && raw !== null) return raw;
    if (typeof raw !== 'string') return null;

    const trimmed = raw.trim();
    const withoutPrefix = trimmed.startsWith('Server:') ? trimmed.slice(7).trim() : trimmed;

    try {
        return JSON.parse(withoutPrefix);
    } catch {
        return null;
    }
}

export default function ChainlitChatPanel({ followUpContext, onClearFollowUp, onCapturedNodes }) {
    const iframeRef = useRef(null);
    const [iframeLoaded, setIframeLoaded] = useState(false);

    const defaultChainlitServer = import.meta.env.DEV
        ? `${window.location.origin}/chainlit`
        : `${window.location.protocol}//${window.location.hostname}:8000`;
    const chainlitAppUrl = import.meta.env.VITE_CHAINLIT_SERVER || defaultChainlitServer;

    const chainlitOrigin = useMemo(() => {
        try {
            return new URL(chainlitAppUrl, window.location.href).origin;
        } catch {
            return window.location.origin;
        }
    }, [chainlitAppUrl]);

    const followUpPrompt = useMemo(() => formatFollowUpContext(followUpContext), [followUpContext]);

    useEffect(() => {
        if (!iframeLoaded || !followUpPrompt || !iframeRef.current?.contentWindow) return;

        const payload = {
            type: 'follow_up_context',
            prompt: followUpPrompt,
            context: followUpContext,
        };
        iframeRef.current.contentWindow.postMessage(`Client: ${JSON.stringify(payload)}`, chainlitOrigin);
    }, [iframeLoaded, followUpPrompt, followUpContext, chainlitOrigin]);

    useEffect(() => {
        const handleWindowMessage = (event) => {
            if (event.origin !== chainlitOrigin) return;

            const payload = parseServerPayload(event.data);
            if (!payload || payload.type !== 'captured_nodes') return;

            onCapturedNodes?.(payload.data || {});
        };

        window.addEventListener('message', handleWindowMessage);
        return () => window.removeEventListener('message', handleWindowMessage);
    }, [chainlitOrigin, onCapturedNodes]);

    return (
        <>
            <div className="panel-header">
                <span className="panel-title">💬 Follow-up</span>
                {followUpContext && (
                    <button className="chat-reset-btn" onClick={onClearFollowUp}>Clear context</button>
                )}
            </div>

            <div className="panel-body chainlit-iframe-wrap">
                {followUpContext && (
                    <div className="chat-context-badge" style={{ margin: '10px 12px 0 12px' }}>
                        <span className="context-icon">🧠</span>
                        <div className="context-text">
                            <span className="context-title">{followUpContext.type}: {followUpContext.title}</span>
                            <div>Follow-up context sent to Chainlit. Ask your question in the chat below.</div>
                        </div>
                    </div>
                )}

                <iframe
                    ref={iframeRef}
                    title="Chainlit Follow-up Chat"
                    src={chainlitAppUrl}
                    className="chainlit-iframe"
                    allow="clipboard-write; microphone; camera"
                    onLoad={() => setIframeLoaded(true)}
                />
            </div>
        </>
    );
}
