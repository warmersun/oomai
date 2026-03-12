export const EMTECH_COLORS = {
    'artificial intelligence': '#a855f7',
    'robots': '#f43f5e',
    'computing': '#06b6d4',
    'energy': '#eab308',
    'crypto-currency': '#f59e0b',
    'networks': '#3b82f6',
    'transportation': '#10b981',
    '3D printing': '#ec4899',
    'internet of things': '#8b5cf6',
    'virtual reality': '#14b8a6',
    'synthetic biology': '#84cc16',
};

export function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export function escapeAttr(str) {
    if (!str) return '';
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

/** Convert markdown text to HTML (used for analysis/chat rendering) */
export function markdownToHtml(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code>${code.trim()}</code></pre>`);
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Headings
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Bold+Italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/(?<!\*)\*([^\*\n]+?)\*(?!\*)/g, '<em>$1</em>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Horizontal rules
    html = html.replace(/^---$/gm, '<hr>');
    // Tables (standard with header)
    html = html.replace(/^ *\|(.+)\|[ \t]*\n *\|([-:| ]+)\|[ \t]*\n((?:.*\|.*(?:\n|$))*)/gm, function (match, header, sep, body) {
        const headers = header.replace(/^ *\||\| *$/g, '').split('|').map(h => `<th>${h.trim()}</th>`).join('');
        const rows = body.trim().split('\n').filter(r => r.trim()).map(row => {
            const cells = row.replace(/^ *\||\| *$/g, '').split('|').map(c => `<td>${c.trim()}</td>`).join('');
            return `<tr>${cells}</tr>`;
        }).join('');
        return `</p><div class="md-table-wrapper"><table class="md-table"><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div><p>\n`;
    });
    // Unordered lists
    html = html.replace(/^[\t ]*[-*+] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>');
    // Ordered lists
    html = html.replace(/^[\t ]*\d+\. (.+)$/gm, '<li>$1</li>');
    // Paragraphs
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/(?<![>\n])\n(?![<\n])/g, '<br>');
    if (!html.startsWith('<')) html = '<p>' + html + '</p>';
    // Cleanup
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<h[123]>)/g, '$1');
    html = html.replace(/(<\/h[123]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<ul>)/g, '$1');
    html = html.replace(/(<\/ul>)<\/p>/g, '$1');
    html = html.replace(/<p>(<pre>)/g, '$1');
    html = html.replace(/(<\/pre>)<\/p>/g, '$1');
    html = html.replace(/<p>(<hr>)<\/p>/g, '$1');
    return html;
}

