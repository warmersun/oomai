import { useEffect, useState } from 'react';

export default function MermaidDiagram() {
  const [svg, setSvg] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  // Basic syntax validation for common Mermaid errors
  const validateMermaidSyntax = (diagramText) => {
    if (!diagramText || typeof diagramText !== 'string') {
      return { isValid: false, error: 'Diagram text is required and must be a string' };
    }

    const trimmed = diagramText.trim();
    if (trimmed.length === 0) {
      return { isValid: false, error: 'Diagram text cannot be empty' };
    }

    // Check for common syntax issues
    const commonErrors = [
      { pattern: /graph\s*$/i, error: 'Graph definition is incomplete - missing direction (TD, LR, etc.)' },
      { pattern: /flowchart\s*$/i, error: 'Flowchart definition is incomplete - missing direction (TD, LR, etc.)' },
      { pattern: /sequenceDiagram\s*$/i, error: 'Sequence diagram is incomplete - missing participants or interactions' },
      { pattern: /classDiagram\s*$/i, error: 'Class diagram is incomplete - missing class definitions' },
      { pattern: /stateDiagram\s*$/i, error: 'State diagram is incomplete - missing states or transitions' },
      { pattern: /erDiagram\s*$/i, error: 'ER diagram is incomplete - missing entities or relationships' },
      { pattern: /gantt\s*$/i, error: 'Gantt chart is incomplete - missing tasks or dates' },
      { pattern: /pie\s*$/i, error: 'Pie chart is incomplete - missing data' },
      { pattern: /gitgraph\s*$/i, error: 'Git graph is incomplete - missing commits or branches' },
      { pattern: /journey\s*$/i, error: 'User journey is incomplete - missing steps' },
      { pattern: /mindmap\s*$/i, error: 'Mind map is incomplete - missing nodes' },
      { pattern: /timeline\s*$/i, error: 'Timeline is incomplete - missing events' },
    ];

    for (const { pattern, error } of commonErrors) {
      if (pattern.test(trimmed)) {
        return { isValid: false, error };
      }
    }

    // Check for unmatched brackets/parentheses
    const openBrackets = (trimmed.match(/\[/g) || []).length;
    const closeBrackets = (trimmed.match(/\]/g) || []).length;
    if (openBrackets !== closeBrackets) {
      return { isValid: false, error: 'Unmatched square brackets in diagram syntax' };
    }

    const openParens = (trimmed.match(/\(/g) || []).length;
    const closeParens = (trimmed.match(/\)/g) || []).length;
    if (openParens !== closeParens) {
      return { isValid: false, error: 'Unmatched parentheses in diagram syntax' };
    }

    return { isValid: true };
  };

  const renderDiagram = async (diagramText, retryAttempt = 0) => {
    if (!window.mermaid) {
      setError('Mermaid library is not loaded. Please refresh the page and try again.');
      return;
    }

    if (!diagramText) {
      setError('No diagram provided');
      return;
    }

    setIsLoading(true);
    setError(null);

    // Validate syntax before attempting to render
    const validation = validateMermaidSyntax(diagramText);
    if (!validation.isValid) {
      setError(validation.error);
      setIsLoading(false);
      return;
    }

    try {
      // Configure MermaidJS globally to suppress error rendering
      window.mermaid.initialize({
        suppressErrorRendering: true,
        logLevel: 'fatal',
        securityLevel: 'loose',
        theme: 'default',
        startOnLoad: false
      });

      // First, validate the diagram syntax using mermaid.parse()
      try {
        const isValid = await window.mermaid.parse(diagramText);
        if (!isValid) {
          setError('Invalid diagram syntax detected');
          setIsLoading(false);
          return;
        }
      } catch (parseError) {
        // Parse failed, handle the error gracefully
        setError('Diagram syntax validation failed: ' + (parseError.message || 'Unknown parse error'));
        setIsLoading(false);
        return;
      }

      // If parsing succeeded, proceed with rendering
      const uniqueId = 'mermaid-' + Math.random().toString(36).substr(2, 9);
      const { svg } = await window.mermaid.render(uniqueId, diagramText);
      
      setSvg(svg);
      setError(null);
    } catch (err) {
      console.error('Mermaid render error:', err);
      
      // Provide more specific error messages based on the error type
      let errorMessage = 'Failed to render diagram';
      
      if (err.message) {
        if (err.message.includes('Parse error')) {
          errorMessage = 'Syntax error in diagram: ' + err.message.replace('Parse error on line', 'Error on line');
        } else if (err.message.includes('Lexical error')) {
          errorMessage = 'Invalid characters in diagram: ' + err.message;
        } else if (err.message.includes('Unknown diagram type')) {
          errorMessage = 'Unknown diagram type. Supported types: graph, flowchart, sequenceDiagram, classDiagram, stateDiagram, erDiagram, gantt, pie, gitgraph, journey, mindmap, timeline';
        } else if (err.message.includes('Invalid direction')) {
          errorMessage = 'Invalid direction specified. Use TD (top-down), LR (left-right), RL (right-left), or BT (bottom-top)';
        } else {
          errorMessage = 'Diagram error: ' + err.message;
        }
      }

      // If this is a retry attempt and we haven't exceeded max retries, try again
      if (retryAttempt < 2) {
        setTimeout(() => {
          setRetryCount(prev => prev + 1);
          renderDiagram(diagramText, retryAttempt + 1);
        }, 1000);
        return;
      }

      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    renderDiagram(props.diagram);
  }, [props.diagram]);


  const handleRetry = () => {
    setRetryCount(0);
    renderDiagram(props.diagram);
  };

  const handlePopOut = () => {
    if (error) {
      alert('Cannot open popup: Diagram has errors that need to be fixed first.');
      return;
    }
    
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
      {/* Toolbar with pop-out and retry */}
      <div style={{ position: 'absolute', top: '5px', right: '5px', zIndex: 1, display: 'flex', gap: '8px' }}>
        {error && (
          <button 
            onClick={handleRetry}
            style={{
              background: '#28a745',
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
              e.target.style.background = '#218838';
              e.target.style.transform = 'translateY(-1px)';
              e.target.style.boxShadow = '0 4px 8px rgba(0,0,0,0.15)';
            }}
            onMouseOut={(e) => {
              e.target.style.background = '#28a745';
              e.target.style.transform = 'translateY(0)';
              e.target.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
            }}
          >
            🔄 Retry
          </button>
        )}
        <button 
          onClick={handlePopOut}
          disabled={!!error}
          style={{
            background: error ? '#6c757d' : '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            padding: '6px 12px',
            fontSize: '12px',
            fontWeight: '500',
            cursor: error ? 'not-allowed' : 'pointer',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
            transition: 'all 0.2s ease',
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            opacity: error ? 0.6 : 1
          }}
          onMouseOver={(e) => {
            if (!error) {
              e.target.style.background = '#0056b3';
              e.target.style.transform = 'translateY(-1px)';
              e.target.style.boxShadow = '0 4px 8px rgba(0,0,0,0.15)';
            }
          }}
          onMouseOut={(e) => {
            if (!error) {
              e.target.style.background = '#007bff';
              e.target.style.transform = 'translateY(0)';
              e.target.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
            }
          }}
        >
          🔍 Pop Out
        </button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '40px 20px',
          color: '#666',
          fontSize: '14px'
        }}>
          <div style={{
            width: '40px',
            height: '40px',
            border: '4px solid #f3f3f3',
            borderTop: '4px solid #007bff',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            marginBottom: '16px'
          }} />
          <div>Rendering diagram...</div>
          {retryCount > 0 && (
            <div style={{ fontSize: '12px', color: '#999', marginTop: '8px' }}>
              Retry attempt {retryCount}
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div style={{
          padding: '20px',
          background: '#f8d7da',
          border: '1px solid #f5c6cb',
          borderRadius: '4px',
          color: '#721c24',
          fontSize: '14px',
          lineHeight: '1.5'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px' }}>
            <span style={{ fontSize: '18px', marginRight: '8px' }}>⚠️</span>
            <strong>Diagram Error</strong>
          </div>
          <div style={{ marginBottom: '12px' }}>{error}</div>
          <div style={{ fontSize: '12px', color: '#856404', background: '#fff3cd', padding: '8px', borderRadius: '4px' }}>
            <strong>Tips:</strong>
            <ul style={{ margin: '8px 0 0 20px', padding: 0 }}>
              <li>Check for typos in diagram syntax</li>
              <li>Ensure all brackets and parentheses are properly closed</li>
              <li>Verify diagram type is supported (graph, flowchart, sequenceDiagram, etc.)</li>
              <li>Make sure direction is specified for graphs and flowcharts (TD, LR, etc.)</li>
            </ul>
          </div>
        </div>
      )}

      {/* Diagram container */}
      {!error && !isLoading && (
        <div
          style={{
            overflow: 'auto',
            maxHeight: '500px', // Adjustable; prevents huge diagrams from overflowing chat
          }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}

      {/* CSS for loading animation */}
      <style jsx>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}