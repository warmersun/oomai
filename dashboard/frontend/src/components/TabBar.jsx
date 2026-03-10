import React, { useRef, useEffect, useCallback } from 'react';

export default function TabBar({ emtechs, currentEmTech, onSelect }) {
    const barRef = useRef(null);
    const wrapperRef = useRef(null);

    const updateArrows = useCallback(() => {
        const bar = barRef.current;
        const wrapper = wrapperRef.current;
        if (!bar || !wrapper) return;
        const canLeft = bar.scrollLeft > 2;
        const canRight = bar.scrollLeft < bar.scrollWidth - bar.clientWidth - 2;
        wrapper.classList.toggle('can-scroll-left', canLeft);
        wrapper.classList.toggle('can-scroll-right', canRight);
        wrapper.querySelector('.tab-bar-arrow.left')?.classList.toggle('visible', canLeft);
        wrapper.querySelector('.tab-bar-arrow.right')?.classList.toggle('visible', canRight);
    }, []);

    useEffect(() => {
        const bar = barRef.current;
        if (!bar) return;
        bar.addEventListener('scroll', updateArrows);
        window.addEventListener('resize', updateArrows);
        requestAnimationFrame(updateArrows);
        return () => {
            bar.removeEventListener('scroll', updateArrows);
            window.removeEventListener('resize', updateArrows);
        };
    }, [updateArrows, emtechs]);

    const scroll = (dir) => {
        barRef.current?.scrollBy({ left: dir * 200, behavior: 'smooth' });
    };

    return (
        <div className="tab-bar-wrapper" ref={wrapperRef}>
            <button className="tab-bar-arrow left" onClick={() => scroll(-1)}>‹</button>
            <nav className="tab-bar" ref={barRef}>
                {emtechs.map((e) => (
                    <div
                        key={e.name}
                        className={`tab ${currentEmTech === e.name ? 'active' : ''}`}
                        onClick={() => onSelect(e.name)}
                    >
                        <span className="tab-icon">{e.icon}</span>
                        {e.name}
                    </div>
                ))}
            </nav>
            <button className="tab-bar-arrow right" onClick={() => scroll(1)}>›</button>
        </div>
    );
}
