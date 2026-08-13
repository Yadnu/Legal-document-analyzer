"use client";

/**
 * Inner PDF renderer — imported dynamically (no SSR) by pdf-viewer.tsx.
 * This component owns the react-pdf Document/Page and worker setup.
 */
import { useCallback } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { Loader2 } from "lucide-react";
import type { CitationOut } from "@/lib/types";

// Served as a static file from /public — no webpack bundling, no Terser issues.
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

interface PdfRendererProps {
  url: string;
  pageNumber: number;
  scale: number;
  activeCitation: CitationOut | null;
  onLoadSuccess: (numPages: number) => void;
}

export default function PdfRenderer({
  url,
  pageNumber,
  scale,
  activeCitation,
  onLoadSuccess,
}: PdfRendererProps) {
  const highlightedQuote = activeCitation?.quote ?? null;

  const customTextRenderer = useCallback(
    ({ str }: { str: string; itemIndex: number }) => {
      if (!highlightedQuote) return str;

      // Attempt to match the first ~40 characters of the quote inside a text chunk.
      // PDF text items rarely hold the entire quote verbatim, so we match a prefix.
      const searchFragment = highlightedQuote.slice(0, 40).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const re = new RegExp(searchFragment, "i");
      if (!re.test(str)) return str;

      return str.replace(
        re,
        (m) => `<mark class="pdf-highlight">${m}</mark>`
      );
    },
    [highlightedQuote]
  );

  return (
    <>
      <Document
        file={url}
        onLoadSuccess={({ numPages }) => onLoadSuccess(numPages)}
        loading={
          <div className="flex items-center gap-2 pt-24 text-ink-muted text-sm">
            <Loader2 size={18} className="animate-spin text-gold" />
            Rendering PDF…
          </div>
        }
        error={
          <p className="pt-24 text-status-failed text-sm text-center max-w-xs">
            Could not load the document. It may still be processing, or the
            preview link has expired — reload the page to refresh it.
          </p>
        }
      >
        <Page
          pageNumber={pageNumber}
          scale={scale}
          customTextRenderer={customTextRenderer}
          renderTextLayer
          renderAnnotationLayer
          className="shadow-[0_8px_40px_rgba(0,0,0,0.6)]"
        />
      </Document>

      {/* Scoped styles for the PDF text layer highlights */}
      <style>{`
        .react-pdf__Page__textContent span { opacity: 0.02; }
        .react-pdf__Page__textContent span:hover { opacity: 0.15; cursor: text; }
        .pdf-highlight {
          background: rgba(212,168,67,0.40);
          border-radius: 2px;
          padding: 0 1px;
          box-shadow: 0 0 0 2px rgba(212,168,67,0.25);
          opacity: 1 !important;
        }
      `}</style>
    </>
  );
}
