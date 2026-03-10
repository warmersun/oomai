import React, { useState } from 'react';
import { postNews, postAnalyze } from '../api';
import { escapeHtml, markdownToHtml } from '../utils';
import { LoadingSpinner, EmptyState } from './shared';

export default function NewsPanel({ currentEmTech, onOpenModal }) {
    const [items, setItems] = useState([]);
    const [topic, setTopic] = useState('');
    const [scanning, setScanning] = useState(false);
    const [placeholder, setPlaceholder] = useState(true);

    const scanNews = async () => {
        if (!currentEmTech) return;
        setScanning(true);
        setPlaceholder(false);
        setItems([]);
        try {
            const body = { emtech: currentEmTech };
            if (topic.trim()) body.topic = topic.trim();
            const data = await postNews(body);
            if (data.items?.length > 0) {
                setItems(data.items);
            } else if (data.raw_content) {
                setItems([{ headline: 'Results', summary: data.raw_content, _raw: true }]);
            } else {
                setItems([]);
            }
        } catch (err) {
            console.error('Scan failed:', err);
        } finally {
            setScanning(false);
        }
    };

    const viewItem = (item, idx) => {
        onOpenModal({
            title: `📡 ${item.headline}`,
            content: item,
            type: 'news',
            idx,
            allItems: items,
            currentEmTech,
        });
    };

    return (
        <>
            <div className="panel-header">
                <span className="panel-title">📡 Latest Intel</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                        type="text"
                        className="intel-topic-input"
                        placeholder="Enter a news topic…"
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') scanNews(); }}
                    />
                    <button
                        className={`scan-btn ${scanning ? 'scanning' : ''}`}
                        disabled={!currentEmTech || scanning}
                        onClick={scanNews}
                    >
                        {scanning ? '⏳ SCANNING…' : '⚡ Scan'}
                    </button>
                </div>
            </div>
            <div className="panel-body">
                {scanning ? (
                    <LoadingSpinner text={topic.trim()
                        ? `SEARCHING: \u201C${escapeHtml(topic.trim())}\u201D…<br>This may take 15-30 seconds`
                        : 'SCANNING X AND WEB…<br>This may take 15-30 seconds'} />
                ) : placeholder ? (
                    <div className="news-placeholder">
                        <span className="radar-icon">📡</span>
                        Select an EmTech and click Scan or enter a topic to gather intelligence
                    </div>
                ) : items.length === 0 ? (
                    <EmptyState>No news found</EmptyState>
                ) : (
                    items.map((item, idx) => {
                        if (item._raw) {
                            return <div key={idx} className="news-content" dangerouslySetInnerHTML={{ __html: markdownToHtml(item.summary) }} />;
                        }
                        const sig = (item.significance || 'medium').toLowerCase();
                        return (
                            <div key={idx} className="news-item" onClick={() => viewItem(item, idx)}>
                                <div className="news-item-header">
                                    <div className="news-item-headline">{item.headline}</div>
                                    <span className={`news-item-sig ${sig}`}>{sig}</span>
                                </div>
                                <div className="news-item-summary">{item.summary}</div>
                                <div className="news-item-meta">
                                    <span>{item.source || ''}{item.date ? ` · ${item.date}` : ''}</span>
                                    <span className="news-item-analyze">VIEW →</span>
                                </div>
                            </div>
                        );
                    })
                )}
            </div>
        </>
    );
}
