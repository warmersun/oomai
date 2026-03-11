import React, { useEffect, useState } from 'react';

export default function MermaidDiagram({ diagram }) {
  const [svg, setSvg] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  const validateMermaidSyntax = (diagramText) => {
    if (!diagramText || typeof diagramText !== 'string') {
      return { isValid: false, error: 'Diagram text is required and must be a string' };
    }

    const trimmed = diagramText.trim();
    if (trimmed.length === 0) {
      return { isValid: false, error: 'Diagram text cannot be empty' };
    }

    const commonErrors = [
      { pattern: /graph\s*$/i, error: 'Graph definition is incomplete' },
      { pattern: /flowchart\s*$/i, error: 'Flowchart definition is incomplete' },
      { pattern: /sequenceDiagram\s*$/i, error: 'Sequence diagram is incomplete' },
      // simplify basic checks
    ];

    for (const { pattern, errorMsg } of commonErrors) {
      if (pattern.test(trimmed)) {
        return { isValid: false, error: errorMsg };
      }
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

    const validation = validateMermaidSyntax(diagramText);
    if (!validation.isValid) {
      setError(validation.error);
      setIsLoading(false);
      return;
    }

    try {
      window.mermaid.initialize({
        suppressErrorRendering: true,
        logLevel: 'fatal',
        securityLevel: 'loose',
        theme: 'default',
        startOnLoad: false
      });

      try {
        const isValid = await window.mermaid.parse(diagramText);
        if (!isValid) {
          setError('Invalid diagram syntax detected');
          setIsLoading(false);
          return;
        }
      } catch (parseError) {
        setError('Diagram syntax validation failed: ' + (parseError.message || 'Unknown parse error'));
        setIsLoading(false);
        return;
      }

      const uniqueId = 'mermaid-' + Math.random().toString(36).substr(2, 9);
      const { svg } = await window.mermaid.render(uniqueId, diagramText);
      
      setSvg(svg);
      setError(null);
    } catch (err) {
      console.error('Mermaid render error:', err);
      let errorMessage = 'Failed to render diagram';
      
      if (err.message) {
        errorMessage = 'Diagram error: ' + err.message;
      }

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
    renderDiagram(diagram);
  }, [diagram]);

  const handleRetry = () => {
    setRetryCount(0);
    renderDiagram(diagram);
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
          <title>Mermaid Diagram</title>
          <style>
            body { margin: 0; background: #f5f5f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; overflow: auto; }
            .diagram-container { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
          </style>
        </head>
        <body>
          <div class="diagram-container">${svg}</div>
        </body>
        </html>
      `);
      popup.document.close();
    }
  };

  return (
    <div style={{ position: 'relative', border: '1px solid var(--border)', padding: '10px', background: 'var(--bg-secondary)', borderRadius: '8px', margin: '12px 0' }}>
      <div style={{ position: 'absolute', top: '5px', right: '5px', zIndex: 1, display: 'flex', gap: '8px' }}>
        {error && (
          <button 
            onClick={handleRetry}
            style={{
              background: '#28a745', color: 'white', border: 'none', borderRadius: '4px',
              padding: '4px 8px', fontSize: '11px', cursor: 'pointer'
            }}
          >
            🔄 Retry
          </button>
        )}
        <button 
          onClick={handlePopOut}
          disabled={!!error}
          style={{
            background: error ? '#6c757d' : '#007bff', color: 'white', border: 'none',
            borderRadius: '4px', padding: '4px 8px', fontSize: '11px', cursor: error ? 'not-allowed' : 'pointer',
            opacity: error ? 0.6 : 1
          }}
        >
          🔍 Pop Out
        </button>
      </div>

      {isLoading && (
        <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>
          <div>Rendering diagram...</div>
        </div>
      )}

      {error && !isLoading && (
        <div style={{ padding: '20px', background: 'rgba(255, 0, 0, 0.1)', border: '1px solid red', borderRadius: '4px', color: 'red', fontSize: '12px' }}>
          <strong>Diagram Error:</strong> {error}
        </div>
      )}

      {!error && !isLoading && (
        <div
          style={{ overflow: 'auto', maxHeight: '500px', display: 'flex', justifyContent: 'center' }}
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}
    </div>
  );
}
