import React, { useState, useEffect, useRef, useCallback } from 'react';
import { GridStack } from 'gridstack';
import 'gridstack/dist/gridstack.min.css';

import Header from './components/Header';
import TabBar from './components/TabBar';
import SearchBar from './components/SearchBar';
import NewsPanel from './components/NewsPanel';
import BetsPanel from './components/BetsPanel';
import IdeasPanel from './components/IdeasPanel';
import TrendExplorer from './components/TrendExplorer';
import ConvergencesPanel from './components/ConvergencesPanel';
import AdvancementPanel from './components/AdvancementPanel';
import ChainlitChatPanel from './components/ChainlitChatPanel';
import Modal from './components/Modal';
import {
    fetchEmTechs, fetchTrends, fetchBets, fetchIdeas, fetchAdvancement, fetchConvergences,
    fetchIdeaDetail, fetchMilestoneDetail, postBetEval, postIdeaCheck, postAnalyze, postPathway
} from './api';
import { escapeHtml, markdownToHtml } from './utils';

class ChatPanelErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError() {
        return { hasError: true };
    }

    componentDidCatch(error) {
        console.error('ChainlitChatPanel crashed:', error);
    }

    render() {
        if (this.state.hasError) {
            return (
                <>
                    <div className="panel-header">
                        <span className="panel-title">💬 Follow-up</span>
                    </div>
                    <div className="panel-body" style={{ padding: '12px', color: 'var(--text-muted)' }}>
                        Chat is temporarily unavailable. Dashboard data is still available.
                    </div>
                </>
            );
        }

        return this.props.children;
    }
}

export default function App() {
    // Global state
    const [emtechs, setEmtechs] = useState([]);
    const [currentEmTech, setCurrentEmTech] = useState(null);
    const [statusText, setStatusText] = useState('INITIALIZING…');
    const [statusOk, setStatusOk] = useState(true);

    // Panel data
    const [trends, setTrends] = useState([]);
    const [bets, setBets] = useState([]);
    const [ideas, setIdeas] = useState([]);
    const [advancement, setAdvancement] = useState([]);
    const [convergences, setConvergences] = useState([]);

    // Original data (for restoring after search)
    const origData = useRef({ trends: [], bets: [], ideas: [], advancement: [], convergences: [] });

    // Loading states
    const [loadingTrends, setLoadingTrends] = useState(false);
    const [loadingBets, setLoadingBets] = useState(false);
    const [loadingIdeas, setLoadingIdeas] = useState(false);
    const [loadingAdv, setLoadingAdv] = useState(false);
    const [loadingConv, setLoadingConv] = useState(false);

    // Search filter badge
    const [filterBadge, setFilterBadge] = useState(null);

    // Modal state
    const [modal, setModal] = useState({ visible: false, title: '', content: null });

    // Chat follow-up context
    const [followUpContext, setFollowUpContext] = useState(null);

    // GridStack ref
    const gridRef = useRef(null);
    const gridElRef = useRef(null);

    // Init GridStack after mount + add collapse/maximize buttons
    useEffect(() => {
        if (gridElRef.current && !gridRef.current) {
            const grid = GridStack.init({
                cellHeight: 60,
                margin: 16,
                handle: '.panel-header',
                animate: true,
                column: 12,
            }, gridElRef.current);
            gridRef.current = grid;

            // ── Collapse / Maximize buttons (ported from original) ──
            const togglePanel = (gsItem) => {
                if (!gsItem || !grid) return;
                const panel = gsItem.querySelector('.panel');
                if (!panel) return;
                if (panel.classList.contains('maximized')) maximizePanel(gsItem);
                const isCollapsed = panel.classList.contains('collapsed');
                if (isCollapsed) {
                    const savedH = parseInt(gsItem.dataset.expandedH) || 5;
                    panel.classList.remove('collapsed');
                    grid.update(gsItem, { h: savedH });
                    gsItem.querySelector('.panel-collapse-btn').title = 'Collapse panel';
                } else {
                    gsItem.dataset.expandedH = gsItem.getAttribute('gs-h') || '5';
                    panel.classList.add('collapsed');
                    grid.update(gsItem, { h: 2 });
                    gsItem.querySelector('.panel-collapse-btn').title = 'Expand panel';
                }
            };

            const maximizePanel = (gsItem) => {
                if (!gsItem || !grid) return;
                const panel = gsItem.querySelector('.panel');
                if (!panel || panel.classList.contains('collapsed')) return;
                const isMaximized = panel.classList.contains('maximized');
                const maxBtn = gsItem.querySelector('.panel-maximize-btn');
                if (isMaximized) {
                    const sW = parseInt(gsItem.dataset.savedW) || 4;
                    const sH = parseInt(gsItem.dataset.savedH) || 5;
                    const sX = parseInt(gsItem.dataset.savedX) || 0;
                    const sY = parseInt(gsItem.dataset.savedY) || 0;
                    panel.classList.remove('maximized');
                    grid.update(gsItem, { w: sW, h: sH, x: sX, y: sY });
                    maxBtn.textContent = '⛶'; maxBtn.title = 'Maximize panel';
                } else {
                    gsItem.dataset.savedW = gsItem.getAttribute('gs-w') || '4';
                    gsItem.dataset.savedH = gsItem.getAttribute('gs-h') || '5';
                    gsItem.dataset.savedX = gsItem.getAttribute('gs-x') || '0';
                    gsItem.dataset.savedY = gsItem.getAttribute('gs-y') || '0';
                    panel.classList.add('maximized');
                    grid.update(gsItem, { w: 12, h: 14, x: 0, y: 0 });
                    maxBtn.textContent = '🗗'; maxBtn.title = 'Restore panel';
                }
            };

            // Inject buttons into every panel header
            document.querySelectorAll('.panel-header').forEach(header => {
                const controls = document.createElement('div');
                controls.className = 'panel-header-controls';

                const maxBtn = document.createElement('button');
                maxBtn.className = 'panel-maximize-btn';
                maxBtn.title = 'Maximize panel';
                maxBtn.textContent = '⛶';
                maxBtn.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); maximizePanel(header.closest('.grid-stack-item')); });
                controls.appendChild(maxBtn);

                const isInitiallyCollapsed = header.closest('.panel')?.classList.contains('collapsed');
                const colBtn = document.createElement('button');
                colBtn.className = 'panel-collapse-btn';
                colBtn.title = isInitiallyCollapsed ? 'Expand panel' : 'Collapse panel';
                colBtn.innerHTML = '<span class="chevron">▼</span>';
                colBtn.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); togglePanel(header.closest('.grid-stack-item')); });
                controls.appendChild(colBtn);

                header.appendChild(controls);

                // Click header to expand when collapsed
                header.addEventListener('click', (e) => {
                    const panel = header.closest('.panel');
                    if (panel && panel.classList.contains('collapsed')) {
                        e.stopPropagation(); e.preventDefault();
                        togglePanel(header.closest('.grid-stack-item'));
                    }
                });
            });
        }
    }, []);

    // Init: fetch emtechs
    useEffect(() => {
        (async () => {
            try {
                const data = await fetchEmTechs();
                setEmtechs(data);
                setStatusText(`ONLINE — ${data.length} EMTECHS`);
                if (data.length > 0) selectEmTech(data[0].name);
            } catch (err) {
                console.error('Init failed:', err);
                setStatusText('CONNECTION LOST');
                setStatusOk(false);
            }
        })();
    }, []);

    // Select an EmTech tab
    const selectEmTech = useCallback(async (name) => {
        setCurrentEmTech(name);
        setFilterBadge(null);

        setLoadingTrends(true);
        setLoadingBets(true);
        setLoadingIdeas(true);
        setLoadingAdv(true);
        setLoadingConv(true);

        const [t, b, i, a, c] = await Promise.all([
            fetchTrends(name), fetchBets(name), fetchIdeas(name),
            fetchAdvancement(name), fetchConvergences(name),
        ]);

        setTrends(t); setBets(b); setIdeas(i); setAdvancement(a); setConvergences(c);
        origData.current = { trends: t, bets: b, ideas: i, advancement: a, convergences: c };

        setLoadingTrends(false);
        setLoadingBets(false);
        setLoadingIdeas(false);
        setLoadingAdv(false);
        setLoadingConv(false);
    }, []);

    // Search results handler
    const handleSearchResults = useCallback((data, query) => {
        const badge = `🔍 "${escapeHtml(query)}"`;
        setFilterBadge(badge);

        if (data.trends) {
            setTrends(data.trends.map(t => ({ name: t.name, description: t.description, score: t.score })));
        }
        if (data.ideas) setIdeas(data.ideas);
        if (data.convergences) setConvergences(data.convergences);
    }, []);

    const handleClearSearch = useCallback(() => {
        setFilterBadge(null);
        setTrends(origData.current.trends);
        setIdeas(origData.current.ideas);
        setConvergences(origData.current.convergences);
        setBets(origData.current.bets);
    }, []);

    // Modal handlers
    const handleCapturedNodes = useCallback((new_nodes) => {
        console.log("🔥 [DEBUG] handleCapturedNodes FIRED with data:", new_nodes);
        setFilterBadge("✨ Newly captured");

        // Replace panel data with only the new nodes (filter view).
        // Empty the panel if there are no new nodes of that type.
        setTrends(new_nodes.trends || []);
        setIdeas(new_nodes.ideas || []);
        setConvergences(new_nodes.convergences || []);
        setBets(new_nodes.bets || []);
        // Capabilities & Milestones are available in new_nodes
        // but have no dedicated dashboard panels currently.
    }, []);

    const openBetModal = async (bet) => {
        setModal({ visible: true, title: bet.name || 'Active Bet', content: { type: 'bet', data: bet, loading: false, evalResult: null } });
    };

    const openIdeaModal = async (name) => {
        setModal({ visible: true, title: '⏳ Loading…', content: { type: 'idea', loading: true } });
        try {
            const data = await fetchIdeaDetail(name);
            setModal({ visible: true, title: `💡 ${data.name}`, content: { type: 'idea', data, loading: false, checkResult: null } });
        } catch (err) {
            setModal({ visible: true, title: 'Error', content: { type: 'error', message: 'Failed to load idea details' } });
        }
    };

    const openNewsModal = (info) => {
        setModal({ visible: true, title: info.title, content: { type: 'news', data: info.content, allItems: info.allItems, idx: info.idx, currentEmTech: info.currentEmTech, analyzeResult: null } });
    };

    const openPathwayModal = async ({ lacName, lacDesc, milestone, capability }) => {
        setModal({
            visible: true,
            title: `🛤️ Pathway: ${lacName}`,
            content: { type: 'pathway', loading: true, lacName }
        });

        try {
            const data = await postPathway({ lac_name: lacName, emtech: currentEmTech });
            setModal({
                visible: true,
                title: `🛤️ Pathway: ${lacName}`,
                content: {
                    type: 'pathway',
                    loading: false,
                    lacName,
                    lacDesc,
                    milestone,
                    capability,
                    result: data.content || null,
                    error: data.detail || null,
                }
            });
        } catch (err) {
            setModal({
                visible: true,
                title: `🛤️ Pathway: ${lacName}`,
                content: {
                    type: 'pathway',
                    loading: false,
                    lacName,
                    lacDesc,
                    milestone,
                    capability,
                    result: null,
                    error: `Analysis failed: ${err.message}`,
                }
            });
        }
    };

    const handleOpenModal = (info) => {
        if (info.type === 'bet') openBetModal(info.data);
        else if (info.type === 'idea') openIdeaModal(info.name);
        else if (info.type === 'news') openNewsModal(info);
        else if (info.type === 'convergence') {
            const c = info.data;
            setModal({ visible: true, title: c.name || 'Convergence', content: { type: 'convergence', data: c } });
        }
    };

    const closeModal = () => setModal({ visible: false, title: '', content: null });

    // Follow-up handler — closes modal and sets context for chat
    const handleFollowUp = (ctx) => {
        closeModal();
        setFollowUpContext(ctx);
        if (gridRef.current && gridElRef.current) {
            const chatItem = gridElRef.current.querySelector('.chat-panel')?.closest('.grid-stack-item');
            if (chatItem) {
                const panel = chatItem.querySelector('.panel');
                if (panel && panel.classList.contains('collapsed')) {
                    const savedH = parseInt(chatItem.dataset.expandedH) || 13;
                    panel.classList.remove('collapsed');
                    gridRef.current.update(chatItem, { h: savedH });
                    const collapseBtn = chatItem.querySelector('.panel-collapse-btn');
                    if (collapseBtn) collapseBtn.title = 'Collapse panel';
                }
            }
        }
    };

    const onFollowUpFromPathway = (pathwayContent) => {
        handleFollowUp({
            type: 'advancement pathway',
            title: pathwayContent.lacName,
            content: pathwayContent.result,
        });
    };

    // Render modal body based on type
    const renderModalBody = () => {
        const c = modal.content;
        if (!c) return null;

        if (c.type === 'bet') {
            const b = c.data;
            const applyBetEvaluation = (updates) => {
                const nextData = {
                    ...b,
                    validations: updates.validations ?? b.validations,
                    invalidations: updates.invalidations ?? b.invalidations,
                    result: updates.result ?? b.result,
                };
                setModal((prev) => ({ ...prev, content: { ...prev.content, data: nextData } }));
                setBets((prevBets) => prevBets.map((item) => (
                    item.name === b.name
                        ? {
                            ...item,
                            validations: updates.validations ?? item.validations,
                            invalidations: updates.invalidations ?? item.invalidations,
                            result: updates.result ?? item.result,
                        }
                        : item
                )));
            };
            const hasValidation = b.validations?.some(v => v.milestone);
            const hasInvalidation = b.invalidations?.some(v => v.source);
            let status, statusClass;
            if (b.result) {
                status = b.result.toLowerCase().includes('invalid') ? '❌ INVALIDATED' : '✅ VALIDATED';
                statusClass = b.result.toLowerCase().includes('invalid') ? 'invalidated' : 'validated';
            } else if (hasValidation) { status = '✅ SIGNAL VALIDATED'; statusClass = 'validated'; }
            else if (hasInvalidation) { status = '❌ SIGNAL AGAINST'; statusClass = 'invalidated'; }
            else { status = '⏳ PENDING'; statusClass = 'pending'; }

            return (
                <>
                    <div className="modal-section">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                            <span className={`bet-status ${statusClass}`}>{status}</span>
                            {b.placed_date && <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Placed: {b.placed_date}</span>}
                        </div>
                    </div>
                    <div className="modal-section">
                        <div className="modal-section-title">Description</div>
                        <div className="modal-section-content">{b.description || 'No description available.'}</div>
                    </div>
                    {b.validations?.length > 0 && (
                        <div className="modal-section">
                            <div className="modal-section-title">Validations</div>
                            <div className="modal-section-content">
                                {b.validations.map((v, i) => (
                                    <div key={i} style={{ marginBottom: '6px' }}>• {v.milestone || v.source || ''}
                                        {v.date && <span style={{ color: 'var(--accent-amber)', fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}> ({v.date})</span>}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {b.invalidations?.length > 0 && (
                        <div className="modal-section">
                            <div className="modal-section-title">Invalidations</div>
                            <div className="modal-section-content">
                                {b.invalidations.map((v, i) => (
                                    <div key={i} style={{ marginBottom: '6px' }}>• {v.source || v.milestone || ''}
                                        {v.date && <span style={{ color: 'var(--accent-amber)', fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}> ({v.date})</span>}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    <BetEvalSection betName={b.name} currentEmTech={currentEmTech} onFollowUp={handleFollowUp} onEvaluationApplied={applyBetEvaluation} />
                </>
            );
        }


        if (c.type === 'pathway') {
            if (c.loading) {
                return (
                    <div className="loading-container">
                        <div className="loading-spinner" style={{ borderTopColor: 'var(--accent-purple)' }}></div>
                        <div className="loading-text" style={{ color: 'var(--accent-purple)' }}>
                            GENERATING PATHWAY…<br />
                            Mapping use case to global problems via AI
                        </div>
                    </div>
                );
            }

            return (
                <>
                    {(c.lacDesc || c.milestone || c.capability) && (
                        <div className="modal-section">
                            <div className="modal-section-title">Context</div>
                            <div className="modal-section-content">
                                {c.lacDesc && <div><strong>Description:</strong> {c.lacDesc}</div>}
                                {c.milestone && <div><strong>Milestone:</strong> {c.milestone}</div>}
                                {c.capability && <div><strong>Capability:</strong> {c.capability}</div>}
                            </div>
                        </div>
                    )}
                    {c.result ? (
                        <div className="modal-section">
                            <div className="analysis-content" dangerouslySetInnerHTML={{ __html: markdownToHtml(c.result) }} />
                            <button className="follow-up-btn" style={{ marginTop: '12px' }} onClick={() => onFollowUpFromPathway(c)}>
                                💬 Follow up in AI Chat
                            </button>
                        </div>
                    ) : (
                        <div className="modal-section">
                            <div className="empty-state">⚠️ {c.error || 'No pathway content returned.'}</div>
                        </div>
                    )}
                </>
            );
        }

        if (c.type === 'idea' && !c.loading) {
            const d = c.data;
            return (
                <>
                    {d.date && (
                        <div className="modal-section">
                            <div className="modal-section-title">Date</div>
                            <div>{d.date}{d.last_updated_date ? ` (updated: ${d.last_updated_date})` : ''}</div>
                        </div>
                    )}
                    <div className="modal-section">
                        <div className="modal-section-title">Description</div>
                        <div className="modal-section-content">{d.description || 'No description'}</div>
                    </div>
                    {d.argument && (
                        <div className="modal-section">
                            <div className="modal-section-title">Argument</div>
                            <div className="modal-section-content">{d.argument}</div>
                        </div>
                    )}
                    {d.assumptions && (
                        <div className="modal-section">
                            <div className="modal-section-title">Assumptions</div>
                            <div className="modal-section-content">{d.assumptions}</div>
                        </div>
                    )}
                    {d.counterargument && (
                        <div className="modal-section">
                            <div className="modal-section-title">Counterargument</div>
                            <div className="modal-section-content">{d.counterargument}</div>
                        </div>
                    )}
                    {d.bets?.filter(b => b.name).length > 0 && (
                        <div className="modal-section">
                            <div className="modal-section-title">Associated Bets</div>
                            <div>{d.bets.filter(b => b.name).map((b, i) => (
                                <span key={i} className="modal-tag ptc">{b.name}{b.placed_date ? ` · ${b.placed_date}` : ''}{b.result ? ` · ${b.result}` : ''}</span>
                            ))}</div>
                        </div>
                    )}
                    {d.capabilities?.filter(cp => cp.name).length > 0 && (
                        <div className="modal-section">
                            <div className="modal-section-title">Related Capabilities</div>
                            <div>{d.capabilities.filter(cp => cp.name).map((cp, i) => (
                                <span key={i} className="modal-tag lac">{cp.name}</span>
                            ))}</div>
                        </div>
                    )}
                    {d.parties?.filter(p => p.name).length > 0 && (
                        <div className="modal-section">
                            <div className="modal-section-title">Related Parties</div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                {d.parties.filter(p => p.name).map((p, i) => (
                                    <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', padding: '8px 12px', background: 'rgba(0,212,255,0.05)', border: '1px solid rgba(0,212,255,0.2)', borderRadius: '6px' }}>
                                        <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.85rem', marginBottom: '4px' }}>👤 {p.name}</span>
                                        {p.description && <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{p.description}</span>}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    <IdeaCheckSection ideaName={d.name} currentEmTech={currentEmTech} onFollowUp={handleFollowUp} />
                </>
            );
        }

        if (c.type === 'idea' && c.loading) {
            return <div className="loading-container"><div className="loading-spinner" /></div>;
        }

        if (c.type === 'news') {
            const item = c.data;
            return (
                <>
                    <div className="modal-section" style={{ marginBottom: '20px' }}>
                        <div className="modal-section-title" style={{ color: 'var(--accent-cyan)', fontWeight: 600, marginBottom: '8px' }}>Summary</div>
                        <div className="modal-section-content" style={{ color: 'var(--text-primary)', lineHeight: 1.5, fontSize: '0.9rem' }}>{item.summary || 'No summary available.'}</div>
                    </div>
                    {(item.source || item.date) && (
                        <div className="modal-section" style={{ marginBottom: '20px' }}>
                            <div className="modal-section-title" style={{ color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase' }}>Source</div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{item.source || ''}{item.date ? ` · ${item.date}` : ''}</div>
                        </div>
                    )}
                    <NewsAnalyzeSection item={item} idx={c.idx} currentEmTech={c.currentEmTech} onFollowUp={handleFollowUp} />
                </>
            );
        }

        if (c.type === 'convergence') {
            const conv = c.data;
            const isAccelerates = conv.direction === 'ACCELERATES';
            const dirClass = isAccelerates ? 'accelerates' : 'accelerated-by';
            const dirLabel = isAccelerates ? '→ accelerates' : '← accelerated by';
            const otherEmtechs = (conv.other_emtechs || []).filter(e => e);

            return (
                <>
                    <div className="modal-section">
                        <div className="modal-section-title">Description</div>
                        <div className="modal-section-content">{conv.description || 'No description available.'}</div>
                    </div>
                    <div className="modal-section">
                        <div className="modal-section-title">Direction</div>
                        <div className="conv-card-meta">
                            <span className={`conv-direction ${dirClass}`}>{dirLabel}</span>
                            {otherEmtechs.map((e, i) => (
                                <span key={i} className="conv-emtech-badge">{e}</span>
                            ))}
                        </div>
                    </div>
                </>
            );
        }

        return null;
    };

    // Paste handler for URLs
    useEffect(() => {
        const handler = (e) => {
            const tag = e.target.tagName.toLowerCase();
            if ((tag === 'input' || tag === 'textarea') && e.target.id !== 'intel-topic-input') return;
            const text = e.clipboardData.getData('text').trim();
            if (text.startsWith('http://') || text.startsWith('https://')) {
                e.preventDefault();
                if (!currentEmTech) return;
                const inp = document.querySelector('.intel-topic-input');
                if (inp) { inp.value = text; inp.dispatchEvent(new Event('input', { bubbles: true })); }
            }
        };
        document.addEventListener('paste', handler);
        return () => document.removeEventListener('paste', handler);
    }, [currentEmTech]);

    return (
        <>
            <Header statusText={statusText} statusOk={statusOk} />
            <TabBar emtechs={emtechs} currentEmTech={currentEmTech} onSelect={selectEmTech} />
            <SearchBar currentEmTech={currentEmTech} onSearchResults={handleSearchResults} onClear={handleClearSearch} />

            <main className="dashboard grid-stack" ref={gridElRef}>
                {/* News Panel */}
                <div className="grid-stack-item" gs-w="8" gs-h="12" gs-x="0" gs-y="0">
                    <section className="grid-stack-item-content panel news-panel">
                        <NewsPanel currentEmTech={currentEmTech} onOpenModal={handleOpenModal} />
                    </section>
                </div>

                {/* Bets Panel */}
                <div className="grid-stack-item" gs-w="4" gs-h="5" gs-x="8" gs-y="0">
                    <section className="grid-stack-item-content panel bets-panel">
                        <BetsPanel bets={bets} loading={loadingBets} filterBadge={filterBadge} onClearFilter={handleClearSearch} onOpenModal={handleOpenModal} />
                    </section>
                </div>

                {/* Ideas Panel */}
                <div className="grid-stack-item" gs-w="4" gs-h="5" gs-x="8" gs-y="7">
                    <section className="grid-stack-item-content panel ideas-panel">
                        <IdeasPanel ideas={ideas} loading={loadingIdeas} filterBadge={filterBadge} onClearFilter={handleClearSearch} onOpenModal={handleOpenModal} />
                    </section>
                </div>

                {/* Follow-up Panel */}
                <div className="grid-stack-item" gs-w="4" gs-h="2" gs-x="8" gs-y="5" data-expanded-h="13">
                    <section className="grid-stack-item-content panel chat-panel collapsed">
                        <ChatPanelErrorBoundary>
                            <ChainlitChatPanel
                                currentEmTech={currentEmTech}
                                followUpContext={followUpContext}
                                onClearFollowUp={() => setFollowUpContext(null)}
                                onCapturedNodes={handleCapturedNodes}
                            />
                        </ChatPanelErrorBoundary>
                    </section>
                </div>

                {/* Advancement Panel */}
                <div className="grid-stack-item" gs-w="12" gs-h="8" gs-x="0" gs-y="12">
                    <section className="grid-stack-item-content panel advancement-panel">
                        <AdvancementPanel advancement={advancement} loading={loadingAdv} currentEmTech={currentEmTech} onPathway={openPathwayModal} />
                    </section>
                </div>

                {/* Chart/Trend Panel */}
                <div className="grid-stack-item" gs-w="6" gs-h="6" gs-x="0" gs-y="20">
                    <section className="grid-stack-item-content panel chart-panel">
                        <TrendExplorer
                            trends={trends} loading={loadingTrends} currentEmTech={currentEmTech}
                            filterBadge={filterBadge} onClearFilter={handleClearSearch} onFollowUp={handleFollowUp}
                        />
                    </section>
                </div>

                {/* Convergences Panel */}
                <div className="grid-stack-item" gs-w="6" gs-h="6" gs-x="6" gs-y="20">
                    <section className="grid-stack-item-content panel convergences-panel">
                        <ConvergencesPanel convergences={convergences} loading={loadingConv} filterBadge={filterBadge} onClearFilter={handleClearSearch} onOpenModal={handleOpenModal} />
                    </section>
                </div>
            </main>

            <Modal visible={modal.visible} title={modal.title} onClose={closeModal}>
                {renderModalBody()}
            </Modal>
        </>
    );
}

/* ─── Inline sub-components for modal actions ─── */

function BetEvalSection({ betName, currentEmTech, onFollowUp, onEvaluationApplied }) {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);

    const evaluate = async () => {
        setLoading(true);
        try {
            const data = await postBetEval({ bet_name: betName, emtech: currentEmTech });
            if (data.content) setResult(data.content);
            if (onEvaluationApplied) {
                onEvaluationApplied({
                    validations: data.validations || [],
                    invalidations: data.invalidations || [],
                    result: data.result || null,
                });
            }
        } catch (err) {
            setResult(`⚠️ Evaluation failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-section">
            <button className={`bet-evaluate-btn ${loading ? 'evaluating' : ''}`} disabled={loading} onClick={evaluate}>
                {loading ? '⏳ Evaluating…' : result ? '✅ Evaluated' : '🔍 Evaluate'}
            </button>
            {result && (
                <div className="bet-eval-result visible" style={{ marginTop: '12px' }}>
                    <div className="analysis-content" dangerouslySetInnerHTML={{ __html: markdownToHtml(result) }} />
                    <button className="follow-up-btn" style={{ marginTop: '12px' }} onClick={() => onFollowUp({ type: 'bet evaluation', title: betName, content: result })}>
                        💬 Follow up in AI Chat
                    </button>
                </div>
            )}
        </div>
    );
}

function IdeaCheckSection({ ideaName, currentEmTech, onFollowUp }) {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);

    const check = async () => {
        setLoading(true);
        try {
            const data = await postIdeaCheck({ idea_name: ideaName, emtech: currentEmTech });
            if (data?.content) {
                setResult(data.content);
            } else if (data?.detail) {
                setResult(`⚠️ ${data.detail}`);
            } else {
                setResult('⚠️ Check failed: unexpected response from server');
            }
        } catch (err) {
            setResult(`⚠️ Check failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-section" style={{ borderTop: '1px solid var(--border)', paddingTop: '16px' }}>
            <button className="check-btn" disabled={loading} onClick={check}>
                {loading ? '⏳ Checking…' : result ? '✅ Checked' : '✅ Check Validity'}
            </button>
            {result && (
                <div style={{ marginTop: '12px' }}>
                    <div className="analysis-content" dangerouslySetInnerHTML={{ __html: markdownToHtml(result) }} />
                    <button className="follow-up-btn" style={{ marginTop: '12px' }} onClick={() => onFollowUp({ type: 'idea check', title: ideaName, content: result })}>
                        💬 Follow up in AI Chat
                    </button>
                </div>
            )}
        </div>
    );
}

function NewsAnalyzeSection({ item, idx, currentEmTech, onFollowUp }) {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);

    const analyze = async () => {
        setLoading(true);
        try {
            const data = await postAnalyze({
                headline: item.headline, summary: item.summary,
                source: item.source, emtech: currentEmTech,
            });
            if (data.content) setResult(data.content);
        } catch (err) {
            setResult(`⚠️ Analysis failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '24px' }}>
            <button className="trend-action-btn primary" disabled={loading} onClick={analyze} style={{ padding: '10px 20px', fontSize: '0.85rem' }}>
                {loading ? '⏳ Analyzing…' : result ? '✅ Analyzed' : '🔍 Analyze Intelligence'}
            </button>
            {result && (
                <>
                    <div className="analysis-content" dangerouslySetInnerHTML={{ __html: markdownToHtml(result) }} />
                    <button className="follow-up-btn" onClick={() => onFollowUp({ type: 'news analysis', title: item.headline, content: result })}>
                        💬 Follow up in AI Chat
                    </button>
                </>
            )}
        </div>
    );
}
