"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Database, MessageSquare } from "lucide-react";
import { getQuota } from "@/lib/api";

function UsageBar({
  used,
  total,
  warn,
}: {
  used: number;
  total: number;
  warn: boolean;
}) {
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-16 h-1.5 rounded-full bg-ink-faint/20 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            warn ? "bg-status-failed" : "bg-gold"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={`text-[10px] tabular-nums ${
          warn ? "text-status-failed" : "text-ink-muted"
        }`}
      >
        {used}/{total}
      </span>
    </div>
  );
}

export function QuotaBar() {
  const { data } = useQuery({
    queryKey: ["quota"],
    queryFn: getQuota,
    staleTime: 60_000,
    // Don't block page render on quota fetch.
    retry: false,
  });

  if (!data) return null;

  const docWarn = data.doc_count / data.doc_quota >= 0.9;
  const qaWarn = data.qa_used / data.qa_quota >= 0.9;
  const anyWarn = docWarn || qaWarn;

  return (
    <div className="flex items-center gap-4 text-xs">
      {anyWarn && (
        <AlertTriangle size={12} className="text-status-failed shrink-0" />
      )}

      <div className="flex items-center gap-1.5" title="Documents used / quota">
        <Database size={10} className="text-ink-muted" />
        <UsageBar
          used={data.doc_count}
          total={data.doc_quota}
          warn={docWarn}
        />
      </div>

      <div
        className="flex items-center gap-1.5"
        title="Monthly Q&A questions used / quota"
      >
        <MessageSquare size={10} className="text-ink-muted" />
        <UsageBar
          used={data.qa_used}
          total={data.qa_quota}
          warn={qaWarn}
        />
      </div>
    </div>
  );
}
