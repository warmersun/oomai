import React, { useEffect, useMemo, useRef, useState } from 'react';

function formatFollowUpContext(followUpContext) {
    if (!followUpContext) return '';
    return `I'm following up on a ${followUpContext.type} about "${followUpContext.title}".\n\nHere is the context:\n\n${followUpContext.content}\n\nMy question/request is:`;
}

export default function ChainlitChatPanel({ followUpContext, onClearFollowUp }) {
    const iframeRef = useRef(null);
    const [iframeLoaded, setIframeLoaded] = useState(false);

    const defaultChainlitServer = import.meta.env.DEV
        ? `${window.location.origin}/chainlit`
        : `${window.location.protocol}//${window.location.hostname}:8000`;
    const chainlitAppUrl = import.meta.env.VITE_CHAINLIT_SERVER || defaultChainlitServer;

    const followUpPrompt = useMemo(() => formatFollowUpContext(followUpContext), [followUpContext]);

    useEffect(() => {
        if (!iframeLoaded || !followUpPrompt || !iframeRef.current?.contentWindow) return;

        iframeRef.current.contentWindow.postMessage(
            {
                source: 'oom-dashboard',
                type: 'follow_up_context',
                prompt: followUpPrompt,
                context: followUpContext,
            },
            '*',
        );
    }, [iframeLoaded, followUpPrompt, followUpContext]);

    const copyPrompt = async () => {
        if (!followUpPrompt) return;
        try {
            await navigator.clipboard.writeText(followUpPrompt);
        } catch (err) {
            console.warn('Unable to copy follow-up context to clipboard', err);
        }
    };

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
                            <div>Context is ready. Ask your follow-up directly in the embedded Chainlit chat.</div>
                            <button
                                className="chat-reset-btn"
                                style={{ marginTop: 8 }}
                                onClick={copyPrompt}
                            >
                                Copy follow-up prompt
                            </button>
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
