import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import {
    useChatSession,
    useChatMessages,
    useChatInteract,
    useChatData,
    useConfig,
    commandsState,
    messagesState,
} from '@chainlit/react-client';
import { useRecoilValue, useSetRecoilState } from 'recoil';
import { markdownToHtml } from '../utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Step types that represent internal processing, not chat messages. */
const STEP_TYPES = new Set(['tool', 'run', 'llm', 'embedding', 'retrieval', 'rerank']);

/** Step names that should never surface as ephemeral status indicators. */
const IGNORED_STEP_NAMES = new Set(['on_chat_start', 'on_message', 'User Message', 'the Knowledge Graph']);

/** Message types that belong in the permanent chat history. */
const CHAT_MSG_TYPES = new Set(['user_message', 'assistant_message', 'system_message']);

/** Step types that mark a "tool boundary" (messages inside these are hidden). */
const TOOL_BOUNDARY_TYPES = new Set(['tool', 'run', 'llm']);

/** Names of steps that should NOT create a tool boundary despite their type. */
const PASSTHROUGH_NAMES = new Set(['on_message', 'on_chat_start']);

// ---------------------------------------------------------------------------
// Icon Map  (Lucide-style SVG icons for slash-command palette)
// ---------------------------------------------------------------------------

const svgProps = { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };

const IconMap = {
    book: <svg {...svgProps}><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>,
    newspaper: <svg {...svgProps}><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2" /><path d="M18 14h-8" /><path d="M15 18h-5" /><path d="M10 6h8v4h-8V6Z" /></svg>,
    'link-2': <svg {...svgProps}><path d="M9 17H7A5 5 0 0 1 7 7h2" /><path d="M15 7h2a5 5 0 1 1 0 10h-2" /><line x1="8" x2="16" y1="12" y2="12" /></svg>,
    'trending-up': <svg {...svgProps}><polyline points="22 7 13.5 15.5 8.5 10.5 2 17" /><polyline points="16 7 22 7 22 13" /></svg>,
    'check-check': <svg {...svgProps}><path d="M18 6 7 17l-5-5" /><path d="m22 10-7.5 7.5L13 16" /></svg>,
    map: <svg {...svgProps}><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" /><line x1="9" x2="9" y1="3" y2="18" /><line x1="15" x2="15" y1="6" y2="21" /></svg>,
    wrench: <svg {...svgProps}><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /></svg>,
    route: <svg {...svgProps}><circle cx="6" cy="19" r="3" /><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15" /><circle cx="18" cy="5" r="3" /></svg>,
    'notebook-text': <svg {...svgProps}><path d="M2 6h4" /><path d="M2 10h4" /><path d="M2 14h4" /><path d="M2 18h4" /><rect width="16" height="20" x="4" y="2" rx="2" /><path d="M9.5 8h5" /><path d="M9.5 12H16" /><path d="M9.5 16H14" /></svg>,
    search: <svg {...svgProps}><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>,
    clock: <svg {...svgProps}><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>,
    'check-circle': <svg {...svgProps}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><path d="m9 11 3 3L22 4" /></svg>,
    'alert-triangle': <svg {...svgProps}><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>,
    'scan-search': <svg {...svgProps}><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><circle cx="12" cy="12" r="3" /><path d="m16 16-1.9-1.9" /></svg>,
    'file-text': <svg {...svgProps}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M10 9H8" /><path d="M16 13H8" /><path d="M16 17H8" /></svg>,
};

const DefaultCmdIcon = <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m13 2-2 2.5h3L12 7" /></svg>;

// ---------------------------------------------------------------------------
// Message-tree helpers (pure functions — no React dependencies)
// ---------------------------------------------------------------------------

/**
 * Walk the nested Chainlit message tree and collect currently-running tool
 * steps (those without an `end` timestamp) as ephemeral status indicators.
 */
function collectActiveTools(msgs, out = []) {
    for (const m of msgs) {
        if (STEP_TYPES.has(m.type) && !m.end && !IGNORED_STEP_NAMES.has(m.name)) {
            // Prefer the human-readable output of the deepest child message
            let text = m.output || m.name;
            if (m.steps?.length) {
                const last = m.steps[m.steps.length - 1];
                if (last.type === 'assistant_message' || last.type === 'system_message') {
                    text = last.output || text;
                }
            }
            out.push({ id: m.id, text: text || 'Processing…' });
        }
        if (m.steps) collectActiveTools(m.steps, out);
    }
    return out;
}

/**
 * Flatten the nested message tree into only the messages that should be
 * permanently visible in the chat history (user / assistant / system).
 * Any message nested inside a real tool boundary is excluded.
 */
function collectPersistentMessages(msgs, insideTool = false, out = []) {
    for (const m of msgs) {
        const isToolBoundary = TOOL_BOUNDARY_TYPES.has(m.type) && !PASSTHROUGH_NAMES.has(m.name);
        const nowInTool = insideTool || isToolBoundary;

        if (!nowInTool && CHAT_MSG_TYPES.has(m.type)) {
            out.push(m);
        }
        if (m.steps) collectPersistentMessages(m.steps, nowInTool, out);
    }
    return out;
}

/** Sort messages chronologically by `createdAt`. */
const byDate = (a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();

// ---------------------------------------------------------------------------
// Sub-components (small, focused render helpers)
// ---------------------------------------------------------------------------

function CustomElement({ el }) {
    if (el.type !== 'custom') return null;

    if (el.name === 'MermaidDiagram' && el.props?.diagram) {
        return (
            <div className="mermaid-container" style={{ margin: '12px 0' }}>
                <pre className="mermaid">{el.props.diagram}</pre>
            </div>
        );
    }
    if (el.name === 'Pathway' && el.props?.data) {
        return (
            <div className="pathway-container" style={{ margin: '12px 0' }}>
                <div className="analysis-content"
                    dangerouslySetInnerHTML={{ __html: markdownToHtml(JSON.stringify(el.props.data, null, 2)) }} />
            </div>
        );
    }
    if (el.name === 'OomVisualizer' && el.props?.monthsPerDoubling) {
        return (
            <div className="oom-visualizer" style={{ margin: '12px 0', padding: '12px', background: 'rgba(0,212,255,0.05)', borderRadius: '8px', border: '1px solid rgba(0,212,255,0.15)' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                    📊 OOM Doubling Rate: {el.props.monthsPerDoubling} months
                </div>
            </div>
        );
    }
    return null;
}

function ActiveToolIndicator({ text }) {
    return (
        <div style={{
            padding: '4px 8px', fontSize: '0.65rem', color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)', display: 'flex', alignItems: 'center', gap: '6px',
            marginLeft: '12px', borderLeft: '2px solid rgba(255,255,255,0.1)',
            marginTop: '4px', marginBottom: '4px',
        }}>
            <div className="chat-typing-dot" style={{ width: 4, height: 4, animationDuration: '2s' }} />
            {text}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ChainlitChatPanel({ currentEmTech, followUpContext, onClearFollowUp }) {
    // --- Chainlit hooks ---
    const { connect, disconnect, chatProfile, setChatProfile, session } = useChatSession();
    const { messages } = useChatMessages();
    const { sendMessage, stopTask } = useChatInteract();
    const { loading, connected, elements } = useChatData();
    const { config } = useConfig();
    const commands = useRecoilValue(commandsState);
    const setMessages = useSetRecoilState(messagesState);

    // --- Local state ---
    const [inputValue, setInputValue] = useState('');
    const [showCommands, setShowCommands] = useState(false);
    const messagesEndRef = useRef(null);
    const hasInitializedSession = useRef(false);
    const commandMenuRef = useRef(null);
    const lastFollowUpContextRef = useRef(null);

    const isConnected = connected === true;
    const chatProfiles = config?.chatProfiles || [];

    const getReadOnlyProfile = useCallback(() => {
        const readOnly = chatProfiles.find(p => p.name === 'Read-Only');
        if (readOnly) return readOnly.name;
        return chatProfiles[0]?.name || 'Read-Only';
    }, [chatProfiles]);

    // --- Derived data (memoised) ---
    const filteredCommands = useMemo(() => {
        if (!inputValue.startsWith('/')) return commands;
        const query = inputValue.slice(1).toLowerCase();
        return commands.filter(cmd =>
            cmd.id.toLowerCase().includes(query) || cmd.description.toLowerCase().includes(query)
        );
    }, [commands, inputValue]);

    const activeTools = useMemo(() => collectActiveTools(messages), [messages]);

    const persistentMessages = useMemo(
        () => collectPersistentMessages(messages).sort(byDate),
        [messages],
    );

    // --- Effects ---

    // Connect once when profiles are available
    useEffect(() => {
        if (!hasInitializedSession.current && chatProfiles.length > 0) {
            hasInitializedSession.current = true;
            const readOnly = chatProfiles.find(p => p.name === 'Read-Only') || chatProfiles[0];
            const startProfile = readOnly ? readOnly.name : 'Read-Only';
            
            setChatProfile(startProfile);
            connect({ userEnv: {} });
        }
    }, [chatProfiles.length]); // Intentionally omitting volatile function dependencies!

    // Disconnect purely on unmount
    useEffect(() => {
        return () => {
            disconnect();
            hasInitializedSession.current = false;
        };
    }, []); // Empty dependency array ensures this is strictly component mount/unmount

    // Auto-scroll within the chat container (not the whole page)
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, [messages]);

    // Toggle command palette when input starts with "/"
    useEffect(() => {
        setShowCommands(inputValue.startsWith('/'));
    }, [inputValue]);

    // Dismiss command palette on outside click
    useEffect(() => {
        const handler = (e) => {
            if (commandMenuRef.current && !commandMenuRef.current.contains(e.target)) {
                setShowCommands(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    // --- Helpers ---

    /** Build the final output string, prepending follow-up context if present. */
    const buildOutput = useCallback((text) => {
        if (!followUpContext) return text;
        const ctx = `I'm following up on a ${followUpContext.type} about "${followUpContext.title}".\n\nHere is the context:\n\n${followUpContext.content}\n\nMy question/request is: ${text}`;
        onClearFollowUp();
        return ctx;
    }, [followUpContext, onClearFollowUp]);

    /** Get custom elements attached to a specific message. */
    const getMessageElements = useCallback(
        (messageId) => (elements || []).filter(el => el.forId === messageId),
        [elements],
    );

    // --- Event handlers ---

    const handleProfileSwitch = useCallback((profileName) => {
        if (chatProfile === profileName) return;
        setChatProfile(profileName);
        session?.socket?.emit('clear_session');
        setMessages([]);
    }, [chatProfile, setChatProfile, setMessages, session]);

    const handleNewChat = useCallback(() => {
        session?.socket?.emit('clear_session');
        setMessages([]);
        setChatProfile(getReadOnlyProfile());
    }, [setMessages, setChatProfile, getReadOnlyProfile, session]);

    // Clear visible chat only when follow-up context meaningfully changes.
    useEffect(() => {
        if (!followUpContext) {
            lastFollowUpContextRef.current = null;
            return;
        }

        const contextKey = `${followUpContext.type}:${followUpContext.title}:${followUpContext.content}`;
        if (lastFollowUpContextRef.current === contextKey) return;

        lastFollowUpContextRef.current = contextKey;
        session?.socket?.emit('clear_session');
        setMessages([]);
        setChatProfile(getReadOnlyProfile());
    }, [followUpContext, session]);

    const handleSend = useCallback((commandId) => {
        const text = inputValue.trim();
        if (!text || loading) return;

        setInputValue('');
        setShowCommands(false);

        const msg = { name: 'user', type: 'user_message', output: buildOutput(text) };
        if (commandId) msg.command = commandId;
        sendMessage(msg, []);
    }, [inputValue, loading, buildOutput, sendMessage]);

    const handleCommandSelect = useCallback((command) => {
        const trailing = inputValue.replace(/^\/\S*\s*/, '').trim();
        setInputValue('');
        setShowCommands(false);

        if (trailing) {
            sendMessage({
                name: 'user', type: 'user_message',
                output: buildOutput(trailing), command: command.id,
            }, []);
        } else {
            setInputValue(`/${command.id} `);
        }
    }, [inputValue, buildOutput, sendMessage]);

    const handleKeyDown = useCallback((e) => {
        if (e.key !== 'Enter' || e.shiftKey) return;
        e.preventDefault();

        const text = inputValue.trim();
        if (text.startsWith('/')) {
            const parts = text.match(/^\/(\S+)\s*(.*)/);
            if (parts) {
                const [, cmdId, content] = parts;
                const matched = commands.find(c => c.id === cmdId);
                if (matched && content) {
                    setInputValue('');
                    setShowCommands(false);
                    sendMessage({
                        name: 'user', type: 'user_message',
                        output: buildOutput(content), command: matched.id,
                    }, []);
                    return;
                }
            }
        }
        handleSend();
    }, [inputValue, commands, buildOutput, sendMessage, handleSend]);

    // --- Render ---

    return (
        <>
            {/* ── Header ───────────────────────────────────────────── */}
            <div className="panel-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className="panel-title">💬 Follow-up</span>
                    {isConnected && (
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-green)', display: 'inline-block' }} />
                    )}
                </div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button onClick={handleNewChat} style={{
                        padding: '4px 8px', fontSize: '0.75rem', borderRadius: '4px',
                        background: 'rgba(255,255,255,0.05)', color: 'var(--text)',
                        border: '1px solid var(--border)', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: '4px',
                    }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14" /><path d="M5 12h14" /></svg>
                        New Chat
                    </button>

                    {chatProfiles.length > 1 && (
                        <div style={{ display: 'flex', gap: '4px' }}>
                            {chatProfiles.map(p => (
                                <button key={p.name} onClick={() => handleProfileSwitch(p.name)} style={{
                                    padding: '3px 8px', fontSize: '0.65rem', fontFamily: 'var(--font-mono)',
                                    borderRadius: '4px', cursor: 'pointer', transition: 'all 0.2s',
                                    border: chatProfile === p.name ? '1px solid var(--accent-cyan)' : '1px solid var(--border)',
                                    background: chatProfile === p.name ? 'rgba(0,212,255,0.15)' : 'transparent',
                                    color: chatProfile === p.name ? 'var(--accent-cyan)' : 'var(--text-muted)',
                                }}>
                                    {p.display_name || p.name}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* ── Body ─────────────────────────────────────────────── */}
            <div className="panel-body" style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>

                {/* Follow-up context badge */}
                {followUpContext && (
                    <div className="chat-context-badge">
                        <span className="context-icon">🔗</span>
                        <div>
                            <span className="context-text">Following up on </span>
                            <span className="context-title">{followUpContext.type}: {followUpContext.title}</span>
                        </div>
                    </div>
                )}

                {/* Messages area */}
                <div className="chat-messages">
                    {/* Welcome state */}
                    {messages.length === 0 && !loading && (
                        <div className="chat-welcome">
                            <span className="chat-welcome-icon">💬</span>
                            {isConnected
                                ? <>Type <strong>/</strong> for commands, or ask about EmTech trends.</>
                                : 'Connecting to AI assistant…'}
                        </div>
                    )}

                    {/* Persistent chat messages */}
                    {persistentMessages.map(msg => {
                        if (!msg.output) return null;
                        const isUser = msg.type === 'user_message';
                        const msgElements = getMessageElements(msg.id);

                        return (
                            <React.Fragment key={msg.id}>
                                <div className={`chat-msg ${isUser ? 'user' : 'assistant'}`}>
                                    {isUser ? (
                                        <>
                                            {msg.command && (
                                                <span style={{
                                                    fontFamily: 'var(--font-mono)', fontSize: '0.65rem',
                                                    color: 'var(--accent-purple)', marginBottom: '4px',
                                                    display: 'flex', alignItems: 'center', gap: '4px',
                                                }}>
                                                    {IconMap[msg.command] || DefaultCmdIcon}
                                                    /{msg.command}
                                                </span>
                                            )}
                                            {msg.output}
                                        </>
                                    ) : (
                                        <div dangerouslySetInnerHTML={{ __html: markdownToHtml(msg.output) }} />
                                    )}
                                </div>
                                {msgElements.map(el => <CustomElement key={el.id} el={el} />)}
                            </React.Fragment>
                        );
                    })}

                    {/* Ephemeral tool-activity indicators */}
                    {activeTools.map(t => <ActiveToolIndicator key={t.id} text={t.text} />)}

                    {/* Typing indicator */}
                    {loading && (
                        <div className="chat-typing">
                            <div className="chat-typing-dot" />
                            <div className="chat-typing-dot" />
                            <div className="chat-typing-dot" />
                        </div>
                    )}

                    <div ref={messagesEndRef} />
                </div>

                {/* Command palette */}
                {showCommands && filteredCommands.length > 0 && (
                    <div ref={commandMenuRef} style={{
                        position: 'absolute', bottom: '60px', left: '12px', right: '12px',
                        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                        borderRadius: '8px', maxHeight: '200px', overflowY: 'auto',
                        boxShadow: '0 -4px 20px rgba(0,0,0,0.4)', zIndex: 100,
                    }}>
                        {filteredCommands.map(cmd => (
                            <div key={cmd.id} onClick={() => handleCommandSelect(cmd)}
                                style={{
                                    padding: '8px 14px', cursor: 'pointer', display: 'flex',
                                    alignItems: 'center', gap: '10px',
                                    borderBottom: '1px solid rgba(255,255,255,0.05)',
                                    transition: 'background 0.15s',
                                }}
                                onMouseEnter={e => e.currentTarget.style.background = 'rgba(0,212,255,0.08)'}
                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                            >
                                <span style={{ fontSize: '0.9rem', color: 'var(--accent-cyan)' }}>
                                    {IconMap[cmd.icon] || IconMap[cmd.id] || '⚡'}
                                </span>
                                <div>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                                        /{cmd.id}
                                    </div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                        {cmd.description}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {/* Input area */}
                <div className="chat-input-area">
                    <input
                        type="text"
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={isConnected ? 'Type / for commands…' : 'Connecting…'}
                        disabled={!isConnected}
                    />
                    {loading ? (
                        <button className="chat-send-btn" onClick={stopTask}>⏹ Stop</button>
                    ) : (
                        <button className="chat-send-btn" onClick={() => handleSend()} disabled={!isConnected || !inputValue.trim()}>
                            Send →
                        </button>
                    )}
                </div>
            </div>
        </>
    );
}
