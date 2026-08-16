"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Loader2, Sparkles } from "lucide-react";
import { getViewUrl } from "@/lib/api";
import type { CitationOut } from "@/lib/types";

// Inner renderer — dynamically loaded (no SSR) to avoid Next.js canvas issues
const PdfRenderer = dynamic(() => import("./pdf-renderer"), { ssr: false });

const MAX_EXPLAIN_CHARS = 2000;

interface SelectionInfo {
  text: string;
  x: number;
  y: number;
}

interface PdfViewerProps {
  documentId: string;
  activeCitation: CitationOut | null;
  onExplainClause?: (text: string) => void;
}

export function PdfViewer({ documentId, activeCitation, onExplainClause }: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.0);
  const [selectionInfo, setSelectionInfo] = useState<SelectionInfo | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: viewData, isLoading: urlLoading } = useQuery({
    queryKey: ["view-url", documentId],
    queryFn: () => getViewUrl(documentId),
    staleTime: 240_000,
    gcTime: 240_000,
  });

  useEffect(() => {
    if (activeCitation) {
      containerRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [activeCitation]);

  // Detect text selection in the PDF text layer
  const handleMouseUp = useCallback(() => {
    const selection = window.getSelection();
    const text = selection?.toString().trim() ?? "";

    if (!text || !selection || selection.rangeCount === 0) {
      setSelectionInfo(null);
      return;
    }

    // Only respond to selections inside our container
    const range = selection.getRangeAt(0);
    const container = containerRef.current;
    if (!container || !container.contains(range.commonAncestorContainer)) {
      setSelectionInfo(null);
      return;
    }

    const rect = range.getBoundingClientRect();
    setSelectionInfo({
      text: text.slice(0, MAX_EXPLAIN_CHARS),
      // Position the button centred above the selection
      x: rect.left + rect.width / 2,
      y: rect.top - 8,
    });
  }, []);

  // Clear selection tooltip when clicking outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      const explainBtn = document.getElementById("explain-clause-btn");
      if (explainBtn && explainBtn.contains(e.target as Node)) return;
      setSelectionInfo(null);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleExplain() {
    if (!selectionInfo || !onExplainClause) return;
    onExplainClause(selectionInfo.text);
    window.getSelection()?.removeAllRanges();
    setSelectionInfo(null);
  }

  return (
    <div className="flex flex-col h-full bg-surface-deep">
      {/* Toolbar */}
      <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-ink-faint/20 bg-surface">
        <button
          onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
          disabled={pageNumber <= 1}
          className="btn-ghost px-2 py-1"
          aria-label="Previous page"
        >
          <ChevronLeft size={16} />
        </button>

        <span className="text-xs font-mono text-ink-muted tabular-nums">
          {pageNumber} / {numPages || "—"}
        </span>

        <button
          onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))}
          disabled={pageNumber >= numPages}
          className="btn-ghost px-2 py-1"
          aria-label="Next page"
        >
          <ChevronRight size={16} />
        </button>

        <div className="w-px h-4 bg-ink-faint/30 mx-1" />

        <button
          onClick={() => setScale((s) => Math.min(2.5, +(s + 0.15).toFixed(2)))}
          className="btn-ghost px-2 py-1"
          aria-label="Zoom in"
        >
          <ZoomIn size={16} />
        </button>

        <span className="text-xs font-mono text-ink-muted tabular-nums w-10 text-center">
          {Math.round(scale * 100)}%
        </span>

        <button
          onClick={() => setScale((s) => Math.max(0.4, +(s - 0.15).toFixed(2)))}
          className="btn-ghost px-2 py-1"
          aria-label="Zoom out"
        >
          <ZoomOut size={16} />
        </button>

        {activeCitation && (
          <>
            <div className="w-px h-4 bg-ink-faint/30 mx-1" />
            <span className="text-xs font-mono text-gold truncate max-w-[220px]">
              ↳ {activeCitation.section ? `§${activeCitation.section}` : "citation"}
            </span>
          </>
        )}
      </div>

      {/* Floating "Explain" tooltip — fixed position so it escapes overflow:hidden */}
      {selectionInfo && onExplainClause && (
        <div
          id="explain-clause-btn"
          style={{
            position: "fixed",
            left: selectionInfo.x,
            top: selectionInfo.y,
            transform: "translate(-50%, -100%)",
            zIndex: 50,
          }}
          className="flex flex-col items-center gap-1 pointer-events-auto"
        >
          <button
            onClick={handleExplain}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                       bg-surface-card border border-gold/40 text-gold text-xs font-sans font-medium
                       shadow-gold hover:bg-gold/10 transition-all duration-150 whitespace-nowrap"
          >
            <Sparkles size={12} />
            Explain in plain English
          </button>
          {/* small arrow */}
          <div className="w-2 h-2 bg-surface-card border-r border-b border-gold/40 rotate-45 -mt-1.5" />
        </div>
      )}

      {/* Canvas area */}
      <div
        ref={containerRef}
        onMouseUp={handleMouseUp}
        className="flex-1 overflow-auto flex justify-center items-start p-6"
        style={{
          background:
            "repeating-linear-gradient(45deg,#0d1117 0px,#0d1117 10px,#0f1419 10px,#0f1419 20px)",
        }}
      >
        {urlLoading && (
          <div className="flex flex-col items-center justify-center gap-3 pt-24 text-ink-muted">
            <Loader2 size={24} className="animate-spin text-gold" />
            <span className="text-sm">Loading document…</span>
          </div>
        )}

        {viewData?.url && (
          <PdfRenderer
            url={viewData.url}
            pageNumber={pageNumber}
            scale={scale}
            activeCitation={activeCitation}
            onLoadSuccess={setNumPages}
          />
        )}
      </div>
    </div>
  );
}
