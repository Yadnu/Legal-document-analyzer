"use client";

import { useQuery } from "@tanstack/react-query";
import { Link2, Loader2, ArrowRight, AlertCircle } from "lucide-react";
import { getChunkRefs } from "@/lib/api";
import type { CitationOut, ResolvedRef } from "@/lib/types";

interface CrossRefPanelProps {
  documentId: string;
  citation: CitationOut;
  onJumpToRef: (citation: CitationOut) => void;
}

function RefRow({
  ref,
  documentId,
  onJump,
}: {
  ref: ResolvedRef;
  documentId: string;
  onJump: (citation: CitationOut) => void;
}) {
  const resolved = !!ref.target_chunk_id;

  return (
    <div className="py-2.5 border-b border-surface-card last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className={`w-1 h-1 rounded-full flex-shrink-0 mt-1 ${
              resolved ? "bg-gold" : "bg-ink-muted/30"
            }`}
          />
          <span className="text-xs font-mono text-ink-muted truncate">
            {ref.raw}
          </span>
        </div>
        {resolved && (
          <button
            onClick={() =>
              onJump({
                document_id: documentId,
                chunk_id: ref.target_chunk_id!,
                section: ref.target_section,
                quote: ref.target_content?.slice(0, 120) ?? "",
              })
            }
            className="flex items-center gap-1 text-[10px] text-gold hover:text-gold/70 transition-colors flex-shrink-0"
          >
            <ArrowRight size={10} />
            Go to clause
          </button>
        )}
      </div>

      {resolved ? (
        <div className="mt-1.5 ml-3 space-y-1">
          {(ref.target_section || ref.target_heading) && (
            <p className="text-[10px] font-mono text-ink-muted/60">
              {ref.target_section ? `§${ref.target_section}` : ""}
              {ref.target_section && ref.target_heading ? " · " : ""}
              {ref.target_heading ?? ""}
              {ref.target_page ? ` · p.${ref.target_page}` : ""}
            </p>
          )}
          {ref.target_content && (
            <p className="text-xs text-ink-muted/70 leading-relaxed line-clamp-3">
              {ref.target_content}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-1 ml-3 text-[10px] text-ink-muted/40 italic">
          Referenced section not found in document
        </p>
      )}
    </div>
  );
}

export function CrossRefPanel({
  documentId,
  citation,
  onJumpToRef,
}: CrossRefPanelProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["chunk-refs", documentId, citation.chunk_id],
    queryFn: () => getChunkRefs(documentId, citation.chunk_id),
    staleTime: 5 * 60_000,
    enabled: !!citation.chunk_id,
  });

  if (isLoading) {
    return (
      <div className="px-4 py-3 flex items-center gap-2 text-ink-muted/60 text-xs">
        <Loader2 size={12} className="animate-spin" />
        Loading cross-references…
      </div>
    );
  }

  if (isError) {
    return (
      <div className="px-4 py-3 flex items-center gap-2 text-status-red/60 text-xs">
        <AlertCircle size={12} />
        Could not load cross-references
      </div>
    );
  }

  if (!data || data.refs.length === 0) return null;

  return (
    <div className="border-t border-surface-card">
      <div className="flex items-center gap-1.5 px-4 pt-3 pb-2">
        <Link2 size={12} className="text-gold" />
        <span className="text-[10px] font-semibold tracking-widest uppercase text-ink-muted">
          Cross-references
        </span>
        <span className="text-[10px] text-ink-muted/40 ml-auto">
          {data.refs.filter((r) => r.target_chunk_id).length}/
          {data.refs.length} resolved
        </span>
      </div>
      <div className="px-4 pb-3">
        {data.refs.map((ref) => (
          <RefRow
            key={ref.raw}
            ref={ref}
            documentId={documentId}
            onJump={onJumpToRef}
          />
        ))}
      </div>
    </div>
  );
}
