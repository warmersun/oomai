const script = document.createElement('script');
script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
script.onload = () => {
  window.mermaid.initialize({ startOnLoad: false, theme: 'default' });
};
script.onerror = (err) => console.error('Failed to load Mermaid:', err);
document.body.appendChild(script);