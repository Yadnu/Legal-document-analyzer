"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Loader2 } from "lucide-react";
import { getViewUrl } from "@/lib/api";
import type { CitationOut } from "@/lib/types";

// Inner renderer — dynamically loaded (no SSR) to avoid Next.js canvas issues
const PdfRenderer = dynamic(() => import("./pdf-renderer"), { ssr: false });

interface PdfViewerProps {
  documentId: string;
  activeCitation: CitationOut | null;
}

export function PdfViewer({ documentId, activeCitation }: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.0);
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

      {/* Canvas area */}
      <div
        ref={containerRef}
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
