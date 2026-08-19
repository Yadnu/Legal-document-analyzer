"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Sparkles, AlertCircle, Loader2, ExternalLink } from "lucide-react";
import { getDocumentSummary } from "@/lib/api";
import type { SummaryField } from "@/lib/types";

interface SummaryCardProps {
  documentId: string;
  onJumpToChunk?: (chunkId: string, quote: string | null) => void;
}

const FIELD_META: Array<{
  key: keyof Omit<
    import("@/lib/types").DocumentSummaryCard,
    "document_id" | "extracted_at"
  >;
  label: string;
  description: string;
}> = [
  { key: "parties", label: "Parties", description: "Who are the contracting parties?" },
  { key: "effective_date", label: "Effective Date", description: "When does the agreement take effect?" },
  { key: "term_length", label: "Term Length", description: "Duration of the agreement." },
  { key: "payment_terms", label: "Payment Terms", description: "Payment schedule and conditions." },
  { key: "termination_rights", label: "Termination Rights", description: "How can each party exit?" },
  { key: "liability_caps", label: "Liability Caps", description: "Limits on financial exposure." },
  { key: "governing_law", label: "Governing Law", description: "Which jurisdiction's laws apply?" },
];

function FieldRow({
  label,
  description,
  field,
  onJump,
}: {
  label: string;
  description: string;
  field: SummaryField;
  onJump?: (chunkId: string, quote: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const hasValue = !!field.value;

  return (
    <div className="border-b border-surface-card last:border-0">
      <button
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors group"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              hasValue ? "bg-gold" : "bg-ink-muted/40"
            }`}
          />
          <span className="text-xs font-semibold tracking-widest uppercase text-ink-muted">
            {label}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-1 min-w-0 justify-end">
          {hasValue ? (
            <span className="text-sm text-ink-base truncate max-w-[280px]">
              {field.value}
            </span>
          ) : (
            <span className="text-sm text-ink-muted/50 italic">Not found</span>
          )}
          <ChevronDown
            size={14}
            className={`flex-shrink-0 text-ink-muted transition-transform duration-200 ${
              open ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-2">
          <p className="text-xs text-ink-muted">{description}</p>
          {hasValue && field.quote && (
            <blockquote className="border-l-2 border-gold/50 pl-3 text-xs text-ink-muted/80 italic leading-relaxed">
              &ldquo;{field.quote}&rdquo;
            </blockquote>
          )}
          {hasValue && field.chunk_id && (
            <div className="flex items-center gap-2 pt-1">
              {field.section && (
                <span className="text-[10px] font-mono bg-surface-card text-ink-muted px-2 py-0.5 rounded">
                  §{field.section}
                </span>
              )}
              {onJump && (
                <button
                  onClick={() => onJump(field.chunk_id!, field.quote ?? null)}
                  className="flex items-center gap-1 text-[10px] text-gold hover:text-gold/70 transition-colors"
                >
                  <ExternalLink size={10} />
                  Jump to clause
                </button>
              )}
            </div>
          )}
          {!hasValue && (
            <p className="text-xs text-ink-muted/60">
              This field could not be extracted from the document.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function SummaryCard({ documentId, onJumpToChunk }: SummaryCardProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["summary", documentId],
    queryFn: () => getDocumentSummary(documentId),
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="card p-6 flex items-center justify-center gap-3 text-ink-muted">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm">Extracting key clauses&hellip;</span>
      </div>
    );
  }

  if (isError) {
    const msg =
      error instanceof Error ? error.message : "Extraction failed.";
    return (
      <div className="card p-4 flex items-start gap-3 text-status-red/80">
        <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium">Could not extract summary</p>
          <p className="text-xs text-ink-muted mt-0.5">{msg}</p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const filledCount = FIELD_META.filter(({ key }) => !!data[key]?.value).length;

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-surface-card">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-gold" />
          <h3 className="text-xs font-semibold tracking-widest uppercase text-ink-muted">
            Summary Card
          </h3>
        </div>
        <span className="text-[10px] text-ink-muted/60">
          {filledCount}/{FIELD_META.length} clauses found
        </span>
      </div>

      {/* Fields */}
      {FIELD_META.map(({ key, label, description }) => (
        <FieldRow
          key={key}
          label={label}
          description={description}
          field={data[key]}
          onJump={onJumpToChunk}
        />
      ))}

      {/* Footer */}
      <div className="px-4 py-2 text-[10px] text-ink-muted/40 border-t border-surface-card">
        AI-extracted · not legal advice · verify against the original document
      </div>
    </div>
  );
}
