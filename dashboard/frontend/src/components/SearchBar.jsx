import React, { useState } from 'react';
import { postMap } from '../api';

export default function SearchBar({ currentEmTech, onSearchResults, onClear }) {
    const [query, setQuery] = useState('');
    const [searching, setSearching] = useState(false);
    const [active, setActive] = useState(false);

    const performSearch = async () => {
        if (!query.trim() || !currentEmTech) return;
        setSearching(true);
        try {
            const data = await postMap({ query: query.trim(), emtech: currentEmTech });
            setActive(true);
            onSearchResults(data, query.trim());
        } catch (err) {
            console.error('Search failed:', err);
        } finally {
            setSearching(false);
        }
    };

    const clearSearch = () => {
        setQuery('');
        setActive(false);
        onClear();
    };

    return (
        <div className="search-bar">
            <input
                type="text"
                placeholder="🔍 Search ideas, trends, predictions, and convergences…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') performSearch(); }}
            />
            <button
                className="search-bar-btn"
                disabled={searching}
                onClick={performSearch}
            >
                {searching ? '⏳…' : '🗺️ Map'}
            </button>
            {active && (
                <>
                    <button className="search-bar-btn clear" onClick={clearSearch}>✕ Clear</button>
                    <span className="search-active-badge">🔍 "{query}"</span>
                </>
            )}
        </div>
    );
}
