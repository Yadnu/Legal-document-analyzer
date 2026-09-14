"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { getAuditLog } from "@/lib/api";
import type { AuditEvent } from "@/lib/types";

const PAGE_SIZE = 50;

// Map action strings to a short human-readable badge colour class.
const ACTION_COLOURS: Record<string, string> = {
  "document.upload": "bg-emerald-500/15 text-emerald-700",
  "qa.ask": "bg-blue-500/15 text-blue-700",
  "obligation.resolved": "bg-purple-500/15 text-purple-700",
  "document.deleted": "bg-red-500/15 text-red-700",
};

function ActionBadge({ action }: { action: string }) {
  const colour =
    ACTION_COLOURS[action] ?? "bg-ink-faint/20 text-ink-muted";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colour}`}
    >
      {action}
    </span>
  );
}

function formatTs(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

export function AuditLogTable() {
  const [offset, setOffset] = useState(0);
  const [actionFilter, setActionFilter] = useState("");

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["audit-log", offset, actionFilter],
    queryFn: () =>
      getAuditLog({
        action: actionFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const items: AuditEvent[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  function handleFilterChange(e: React.ChangeEvent<HTMLInputElement>) {
    setActionFilter(e.target.value);
    setOffset(0);
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Filter by action (e.g. qa.ask)"
          value={actionFilter}
          onChange={handleFilterChange}
          className="flex-1 rounded-lg border border-ink-faint/30 bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-gold/60"
        />
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          title="Refresh"
          className="p-1.5 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
        >
          {isFetching ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <RefreshCw size={15} />
          )}
        </button>
      </div>

      {/* Error state */}
      {isError && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">
          <AlertCircle size={15} />
          <span>
            Failed to load audit log. You may need admin permissions to view
            this page.
          </span>
        </div>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div className="flex items-center justify-center py-12 text-ink-muted gap-2">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Loading audit events…</span>
        </div>
      )}

      {/* Table */}
      {!isLoading && !isError && (
        <>
          <div className="rounded-xl border border-ink-faint/20 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-surface-card border-b border-ink-faint/20">
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Timestamp
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    User
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Action
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Resource
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-faint/10">
                {items.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-8 text-center text-sm text-ink-muted"
                    >
                      No audit events found
                      {actionFilter ? ` for action "${actionFilter}"` : ""}.
                    </td>
                  </tr>
                ) : (
                  items.map((ev) => (
                    <tr
                      key={ev.id}
                      className="hover:bg-surface-card/50 transition-colors"
                    >
                      <td className="px-4 py-2.5 text-ink-muted whitespace-nowrap">
                        {formatTs(ev.created_at)}
                      </td>
                      <td className="px-4 py-2.5 text-ink font-mono text-xs truncate max-w-[140px]">
                        {ev.user_id}
                      </td>
                      <td className="px-4 py-2.5">
                        <ActionBadge action={ev.action} />
                      </td>
                      <td className="px-4 py-2.5 text-ink-muted text-xs font-mono truncate max-w-[160px]">
                        {ev.resource_type && ev.resource_id
                          ? `${ev.resource_type}/${ev.resource_id.slice(0, 8)}`
                          : ev.resource_type ?? "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between text-xs text-ink-muted">
              <span>
                {total} event{total !== 1 ? "s" : ""} total · page {currentPage}{" "}
                of {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40 transition-colors"
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40 transition-colors"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
