import { useEffect, useState } from 'react';

export default function MermaidDiagram() {
  const [svg, setSvg] = useState('');

  useEffect(() => {
    if (!window.mermaid) {
      console.error('Mermaid not loaded');
      return;
    }

    const uniqueId = 'mermaid-' + Math.random().toString(36).substr(2, 9);
    window.mermaid.render(uniqueId, props.diagram)
      .then(({ svg }) => setSvg(svg))
      .catch((err) => console.error('Mermaid render error:', err));
  }, [props.diagram]);

  const handlePopOut = () => {
    const popup = window.open('', '_blank', 'width=800,height=600');
    if (popup) {
      popup.document.write(`
        <html>
          <head><title>Mermaid Diagram</title></head>
          <body style="margin:0; display:flex; justify-content:center; align-items:center; height:100vh; background:#f0f0f0;">
            ${svg}
          </body>
        </html>
      `);
      popup.document.close();
    }
  };

  return (
    <div style={{ position: 'relative', border: '1px solid #ccc', padding: '10px', background: '#fff' }}>
      {/* Toolbar with only pop-out */}
      <div style={{ position: 'absolute', top: '5px', right: '5px', zIndex: 1 }}>
        <button onClick={handlePopOut}>Pop Out</button>
      </div>
      {/* Diagram container (no zoom) */}
      <div
        style={{
          overflow: 'auto',
          maxHeight: '500px', // Adjustable; prevents huge diagrams from overflowing chat
        }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
}