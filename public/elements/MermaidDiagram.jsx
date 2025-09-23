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
    const popup = window.open('', '_blank', 'width=1200,height=800');
    if (popup) {
      popup.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
          <title>Mermaid Diagram - Interactive View</title>
          <style>
            * {
              margin: 0;
              padding: 0;
              box-sizing: border-box;
            }
            
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
              background: #f5f5f5;
              overflow: hidden;
            }
            
            .toolbar {
              position: fixed;
              top: 10px;
              left: 10px;
              z-index: 1000;
              background: rgba(255, 255, 255, 0.95);
              border-radius: 8px;
              padding: 10px;
              box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
              display: flex;
              gap: 8px;
              align-items: center;
            }
            
            .toolbar button {
              padding: 8px 12px;
              border: 1px solid #ddd;
              border-radius: 4px;
              background: white;
              cursor: pointer;
              font-size: 14px;
              transition: all 0.2s;
            }
            
            .toolbar button:hover {
              background: #f0f0f0;
              border-color: #999;
            }
            
            .toolbar button:active {
              background: #e0e0e0;
            }
            
            .zoom-info {
              font-size: 12px;
              color: #666;
              min-width: 80px;
              text-align: center;
            }
            
            .diagram-container {
              width: 100vw;
              height: 100vh;
              display: flex;
              justify-content: center;
              align-items: center;
              cursor: grab;
              user-select: none;
            }
            
            .diagram-container.dragging {
              cursor: grabbing;
            }
            
            .diagram-svg {
              transition: transform 0.1s ease-out;
              max-width: none;
              max-height: none;
            }
            
            .instructions {
              position: fixed;
              bottom: 10px;
              right: 10px;
              background: rgba(0, 0, 0, 0.8);
              color: white;
              padding: 10px;
              border-radius: 4px;
              font-size: 12px;
              z-index: 1000;
            }
          </style>
        </head>
        <body>
          <div class="toolbar">
            <button onclick="zoomIn()">Zoom In</button>
            <button onclick="zoomOut()">Zoom Out</button>
            <button onclick="resetZoom()">Reset</button>
            <div class="zoom-info" id="zoomInfo">100%</div>
            <button onclick="fitToScreen()">Fit Screen</button>
          </div>
          
          <div class="diagram-container" id="diagramContainer">
            <div id="diagramWrapper">
              ${svg}
            </div>
          </div>
          
          <div class="instructions">
            Mouse wheel: Zoom<br>
            Drag: Pan<br>
            Double-click: Reset zoom
          </div>
          
          <script>
            let scale = 1;
            let translateX = 0;
            let translateY = 0;
            let isDragging = false;
            let lastX = 0;
            let lastY = 0;
            
            const diagramContainer = document.getElementById('diagramContainer');
            const diagramWrapper = document.getElementById('diagramWrapper');
            const zoomInfo = document.getElementById('zoomInfo');
            const svg = diagramWrapper.querySelector('svg');
            
            if (svg) {
              svg.classList.add('diagram-svg');
            }
            
            function updateTransform() {
              if (svg) {
                svg.style.transform = \`scale(\${scale}) translate(\${translateX}px, \${translateY}px)\`;
              }
              zoomInfo.textContent = Math.round(scale * 100) + '%';
            }
            
            function zoomIn() {
              scale = Math.min(scale * 1.2, 5);
              updateTransform();
            }
            
            function zoomOut() {
              scale = Math.max(scale / 1.2, 0.1);
              updateTransform();
            }
            
            function resetZoom() {
              scale = 1;
              translateX = 0;
              translateY = 0;
              updateTransform();
            }
            
            function fitToScreen() {
              if (!svg) return;
              
              const containerRect = diagramContainer.getBoundingClientRect();
              const svgRect = svg.getBoundingClientRect();
              
              const scaleX = containerRect.width / svgRect.width;
              const scaleY = containerRect.height / svgRect.height;
              scale = Math.min(scaleX, scaleY) * 0.9; // 90% to leave some margin
              
              translateX = 0;
              translateY = 0;
              updateTransform();
            }
            
            // Mouse wheel zoom
            diagramContainer.addEventListener('wheel', (e) => {
              e.preventDefault();
              const delta = e.deltaY > 0 ? 0.9 : 1.1;
              const newScale = scale * delta;
              
              if (newScale >= 0.1 && newScale <= 5) {
                // Zoom towards mouse position
                const rect = diagramContainer.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;
                
                const zoomFactor = newScale / scale;
                translateX = mouseX - (mouseX - translateX) * zoomFactor;
                translateY = mouseY - (mouseY - translateY) * zoomFactor;
                
                scale = newScale;
                updateTransform();
              }
            });
            
            // Drag to pan
            diagramContainer.addEventListener('mousedown', (e) => {
              if (e.button === 0) { // Left mouse button
                isDragging = true;
                diagramContainer.classList.add('dragging');
                lastX = e.clientX;
                lastY = e.clientY;
                e.preventDefault();
              }
            });
            
            document.addEventListener('mousemove', (e) => {
              if (isDragging) {
                const deltaX = e.clientX - lastX;
                const deltaY = e.clientY - lastY;
                
                translateX += deltaX;
                translateY += deltaY;
                
                lastX = e.clientX;
                lastY = e.clientY;
                
                updateTransform();
              }
            });
            
            document.addEventListener('mouseup', () => {
              isDragging = false;
              diagramContainer.classList.remove('dragging');
            });
            
            // Double-click to reset
            diagramContainer.addEventListener('dblclick', resetZoom);
            
            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
              if (e.key === '+' || e.key === '=') {
                e.preventDefault();
                zoomIn();
              } else if (e.key === '-') {
                e.preventDefault();
                zoomOut();
              } else if (e.key === '0') {
                e.preventDefault();
                resetZoom();
              } else if (e.key === 'f' || e.key === 'F') {
                e.preventDefault();
                fitToScreen();
              }
            });
            
            // Initial fit to screen
            setTimeout(fitToScreen, 100);
          </script>
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
        <button 
          onClick={handlePopOut}
          style={{
            background: '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            padding: '6px 12px',
            fontSize: '12px',
            fontWeight: '500',
            cursor: 'pointer',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
            transition: 'all 0.2s ease',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
          }}
          onMouseOver={(e) => {
            e.target.style.background = '#0056b3';
            e.target.style.transform = 'translateY(-1px)';
            e.target.style.boxShadow = '0 4px 8px rgba(0,0,0,0.15)';
          }}
          onMouseOut={(e) => {
            e.target.style.background = '#007bff';
            e.target.style.transform = 'translateY(0)';
            e.target.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
          }}
        >
          🔍 Pop Out
        </button>
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