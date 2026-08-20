"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowLeft, Scale, Info } from "lucide-react";
import { getDocument } from "@/lib/api";
import type { CitationOut } from "@/lib/types";
import { PdfViewer } from "./pdf-viewer";
import { ChatPanel } from "./chat-panel";
import { SummaryCard } from "./summary-card";

interface DocLayoutProps {
  documentId: string;
}

export function DocLayout({ documentId }: DocLayoutProps) {
  const [activeCitation, setActiveCitation] = useState<CitationOut | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);

  const { data: doc } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => getDocument(documentId),
  });

  function handleCitationClick(citation: CitationOut) {
    setActiveCitation((prev) =>
      prev?.chunk_id === citation.chunk_id ? null : citation
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top nav */}
      <header className="shrink-0 border-b border-ink-faint/20 bg-surface/90 backdrop-blur-sm z-10">
        <div className="px-4 h-12 flex items-center gap-3">
          <Link href="/workspace" className="btn-ghost px-2 py-1 text-ink-muted">
            <ArrowLeft size={15} />
            Workspace
          </Link>

          <div className="w-px h-4 bg-ink-faint/30" />

          <Scale size={16} className="text-gold" />
          <span className="font-display text-sm font-medium text-ink truncate">
            {doc?.title ?? "Loading…"}
          </span>

          {doc?.status === "ready" && (
            <span className="ml-auto shrink-0 status-badge bg-status-ready/10 text-status-ready border border-status-ready/25">
              Ready
            </span>
          )}
        </div>
      </header>

      {/* Disclaimer */}
      <div className="shrink-0 disclaimer-bar rounded-none border-x-0 border-t-0 px-4 py-1.5">
        <Info size={12} className="text-gold shrink-0" />
        Document comprehension only — not legal advice. Consult a qualified attorney for legal guidance.
      </div>

      {/* Split view */}
      <div className="flex-1 min-h-0 grid grid-cols-[1fr_420px]">
        {/* PDF viewer — left panel */}
        <PdfViewer
          documentId={documentId}
          activeCitation={activeCitation}
          onExplainClause={(text) =>
            setPendingQuestion(
              `Explain this clause in plain English:\n\n"${text}"`
            )
          }
        />

        {/* Right panel: summary card + chat */}
        <div className="flex flex-col overflow-hidden border-l border-surface-card">
          {/* Summary card — collapsible strip at the top */}
          <div className="shrink-0 overflow-y-auto max-h-[45%] border-b border-surface-card">
            <SummaryCard
              documentId={documentId}
              onJumpToChunk={(chunkId, quote) => {
                // Highlight the clause in the PDF viewer
                setActiveCitation({
                  document_id: documentId,
                  chunk_id: chunkId,
                  section: null,
                  quote: quote ?? "",
                });
              }}
            />
          </div>

          {/* Chat panel */}
          <ChatPanel
            documentId={documentId}
            onCitationClick={handleCitationClick}
            pendingQuestion={pendingQuestion}
            onQuestionConsumed={() => setPendingQuestion(null)}
          />
        </div>
      </div>
    </div>
  );
}
