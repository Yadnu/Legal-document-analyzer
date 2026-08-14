"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { FileText, AlertCircle, Clock, CheckCircle2 } from "lucide-react";
import { listDocuments } from "@/lib/api";
import type { DocumentSummary } from "@/lib/types";
import { UploadButton } from "./upload-button";

function StatusBadge({ status }: { status: DocumentSummary["status"] }) {
  const cfg = {
    ready: {
      icon: CheckCircle2,
      label: "Ready",
      cls: "bg-status-ready/10 text-status-ready border-status-ready/25",
    },
    processing: {
      icon: Clock,
      label: "Processing",
      cls: "bg-status-processing/10 text-status-processing border-status-processing/25",
    },
    failed: {
      icon: AlertCircle,
      label: "Failed",
      cls: "bg-status-failed/10 text-status-failed border-status-failed/25",
    },
  }[status];

  const Icon = cfg.icon;
  return (
    <span className={`status-badge border ${cfg.cls}`}>
      <Icon size={11} />
      {cfg.label}
    </span>
  );
}

function DocumentCard({ doc }: { doc: DocumentSummary }) {
  const isReady = doc.status === "ready";
  const createdAt = new Date(doc.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  const inner = (
    <div className="card px-4 py-3.5 flex items-center gap-3 group transition-all duration-150 hover:border-gold/30 hover:bg-surface-hover">
      <div className="shrink-0 w-9 h-9 rounded-lg bg-gold/10 border border-gold/20 flex items-center justify-center text-gold group-hover:bg-gold/15 transition-colors">
        <FileText size={16} />
      </div>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink truncate leading-snug">
          {doc.title}
        </p>
        <p className="text-xs text-ink-muted font-mono mt-0.5">{createdAt}</p>
      </div>

      <StatusBadge status={doc.status} />
    </div>
  );

  if (isReady) {
    return (
      <Link href={`/workspace/${doc.id}`} className="block">
        {inner}
      </Link>
    );
  }
  return <div className="cursor-default">{inner}</div>;
}

export function DocumentList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
    refetchInterval: (query) => {
      const docs = query.state.data;
      if (!docs) return 5000;
      const anyProcessing = docs.some((d) => d.status === "processing");
      return anyProcessing ? 3000 : false;
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-xl text-ink">Your documents</h2>
        <UploadButton />
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="card h-16 animate-pulse-slow bg-surface-hover"
            />
          ))}
        </div>
      )}

      {isError && (
        <div className="disclaimer-bar text-status-failed border-status-failed/20 bg-status-failed/5">
          <AlertCircle size={14} />
          Failed to load documents. Please refresh.
        </div>
      )}

      {data && data.length === 0 && (
        <div className="card px-6 py-12 flex flex-col items-center gap-3 text-center border-dashed">
          <div className="w-12 h-12 rounded-full bg-gold/10 border border-gold/20 flex items-center justify-center text-gold">
            <FileText size={22} />
          </div>
          <p className="text-ink-muted text-sm">
            No documents yet. Upload a PDF or Word file to get started.
          </p>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((doc) => (
            <DocumentCard key={doc.id} doc={doc} />
          ))}
        </div>
      )}
    </div>
  );
}
