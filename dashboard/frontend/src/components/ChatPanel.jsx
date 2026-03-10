import React, { useState, useRef, useEffect } from 'react';
import { postChatStream, postXArticleStream, postCaptureStream, postChatReset } from '../api';
import { markdownToHtml, processSSEStream, generateSessionId } from '../utils';

export default function ChatPanel({
    currentEmTech, followUpContext, onClearFollowUp, onCapturedNodes, collapsed, disabled
}) {
    const [messages, setMessages] = useState([]);
    const [inputVal, setInputVal] = useState('');
    const [sending, setSending] = useState(false);
    const [sessionId, setSessionId] = useState(null);
    const msgsRef = useRef(null);
    const followUpRef = useRef(followUpContext);

    useEffect(() => { followUpRef.current = followUpContext; }, [followUpContext]);

    const scrollToBottom = () => {
        if (msgsRef.current) msgsRef.current.scrollTop = msgsRef.current.scrollHeight;
    };

    useEffect(scrollToBottom, [messages]);

    const addMsg = (type, content) => {
        setMessages(prev => [...prev, { type, content, id: Date.now() + Math.random() }]);
    };

    const removeByType = (type) => {
        setMessages(prev => prev.filter(m => m.type !== type));
    };

    const handleSSE = (response, onDone) => {
        let lastProgressId = null;

        return processSSEStream(response, {
            session: (e) => setSessionId(e.session_id),
            status: (e) => {
                setMessages(prev => prev.filter(m => m.type !== 'progress'));
                addMsg('status', e.content);
            },
            progress: (e) => {
                setMessages(prev => {
                    const filtered = prev.filter(m => m.id !== lastProgressId);
                    const newMsg = { type: 'progress', content: e.content, id: Date.now() + Math.random() };
                    lastProgressId = newMsg.id;
                    return [...filtered, newMsg];
                });
            },
            message: (e) => {
                setMessages(prev => prev.filter(m => m.type !== 'status' && m.type !== 'progress'));
                addMsg('assistant', e.content);
                onDone?.();
            },
            error: (e) => {
                setMessages(prev => prev.filter(m => m.type !== 'progress'));
                addMsg('error', e.content);
                onDone?.();
            },
            captured_nodes: (e) => onCapturedNodes?.(e.content),
        });
    };

    const sendMessage = async () => {
        if (sending || !inputVal.trim()) return;
        setSending(true);
        const message = inputVal.trim();
        setInputVal('');
        addMsg('user', message);

        try {
            const body = { message, emtech: currentEmTech, session_id: sessionId || generateSessionId() };
            if (followUpRef.current) {
                body.context = `The user is following up on a previous AI ${followUpRef.current.type} of "${followUpRef.current.title}". Here is the full analysis content:\n\n${followUpRef.current.content}`;
                onClearFollowUp?.();
            }
            const response = await postChatStream(body);
            await handleSSE(response);
        } catch (err) {
            addMsg('error', `❌ Connection error: ${err.message}`);
        } finally {
            setSending(false);
        }
    };

    const draftXArticle = async () => {
        if (sending) return;
        setSending(true);
        addMsg('user', '📝 Draft X Article');
        try {
            const body = { session_id: sessionId, emtech: currentEmTech };
            if (followUpRef.current) {
                body.context = `The user is following up on a previous AI ${followUpRef.current.type} of "${followUpRef.current.title}". Here is the full analysis content:\n\n${followUpRef.current.content}`;
            }
            const response = await postXArticleStream(body);
            await handleSSE(response);
        } catch (err) {
            addMsg('error', `❌ Connection error: ${err.message}`);
        } finally {
            setSending(false);
        }
    };

    const captureInKG = async () => {
        if (sending) return;
        setSending(true);
        addMsg('user', '🧠 Capture in KG');
        try {
            const body = { session_id: sessionId, emtech: currentEmTech };
            if (followUpRef.current) {
                body.context = `The user is following up on a previous AI ${followUpRef.current.type} of "${followUpRef.current.title}". Here is the full analysis content:\n\n${followUpRef.current.content}`;
            }
            const response = await postCaptureStream(body);
            await handleSSE(response);
        } catch (err) {
            addMsg('error', `❌ Connection error: ${err.message}`);
        } finally {
            setSending(false);
        }
    };

    const resetChat = async () => {
        if (sessionId) {
            try { await postChatReset({ session_id: sessionId }); } catch (e) { /* ignore */ }
        }
        setSessionId(null);
        setMessages([]);
        onClearFollowUp?.();
    };

    const panelClasses = ['panel', 'chat-panel'];
    if (collapsed) panelClasses.push('collapsed');
    if (disabled && !followUpContext) panelClasses.push('disabled');

    return (
        <>
            <div className="panel-header">
                <span className="panel-title">💬 Follow-up</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <button className="chat-xarticle-btn" onClick={draftXArticle} disabled={sending}>
                        📝 Draft X Article
                    </button>
                    <button className="chat-capture-btn" onClick={captureInKG} disabled={sending}>
                        🧠 Capture in KG
                    </button>
                    <button className="chat-reset-btn" onClick={resetChat}>🔄 Reset</button>
                </div>
            </div>
            <div className="panel-body">
                <div className="chat-messages" ref={msgsRef}>
                    {messages.length === 0 ? (
                        <div className="chat-welcome">
                            <span className="chat-welcome-icon">💬</span>
                            Click <strong>"Follow up in AI Chat"</strong> on any<br />
                            AI analysis result to start a conversation.
                        </div>
                    ) : messages.map((msg) => (
                        <div key={msg.id} className={`chat-msg ${msg.type}`}>
                            {msg.type === 'assistant'
                                ? <div dangerouslySetInnerHTML={{ __html: markdownToHtml(msg.content) }} />
                                : msg.content
                            }
                        </div>
                    ))}
                </div>
                <div className="chat-input-area">
                    <input
                        type="text"
                        placeholder="Ask a follow-up question…"
                        value={inputVal}
                        onChange={(e) => setInputVal(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) sendMessage(); }}
                    />
                    <button className="chat-send-btn" disabled={sending} onClick={sendMessage}>Send</button>
                </div>
            </div>
        </>
    );
}
