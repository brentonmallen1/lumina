import { useEffect, useRef, useCallback } from 'react';
import { Transformer } from 'markmap-lib';
import { Markmap } from 'markmap-view';
import './MindMapDiagram.css';

interface Props {
  markdown: string;
  className?: string;
}

const transformer = new Transformer();

export default function MindMapDiagram({ markdown, className }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const markmapRef = useRef<Markmap | null>(null);

  useEffect(() => {
    if (!svgRef.current || !markdown.trim()) return;

    const { root } = transformer.transform(markdown);

    if (markmapRef.current) {
      // Update existing instance
      markmapRef.current.setData(root);
      markmapRef.current.fit();
    } else {
      // Create new instance with options
      markmapRef.current = Markmap.create(svgRef.current, {
        autoFit: true,
        duration: 300,
        maxWidth: 300,
        paddingX: 16,
      }, root);
    }
  }, [markdown]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (markmapRef.current) {
        markmapRef.current.destroy();
        markmapRef.current = null;
      }
    };
  }, []);

  // Expose fit function for resize handling
  const handleFit = useCallback(() => {
    markmapRef.current?.fit();
  }, []);

  return (
    <div className={`mindmap-container ${className ?? ''}`}>
      <svg ref={svgRef} className="mindmap-svg" />
      <div className="mindmap-controls">
        <button
          className="mindmap-control-btn"
          onClick={handleFit}
          title="Fit to view"
          aria-label="Fit diagram to view"
        >
          Fit
        </button>
      </div>
    </div>
  );
}
