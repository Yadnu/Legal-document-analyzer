"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  Loader2,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import {
  extractObligations,
  listDocumentObligations,
  resolveObligation,
} from "@/lib/api";
import type { Obligation } from "@/lib/types";

const PAGE_SIZE = 20;

const TYPE_COLOURS: Record<string, string> = {
  payment: "bg-emerald-500/15 text-emerald-700",
  notice: "bg-blue-500/15 text-blue-700",
  renewal: "bg-purple-500/15 text-purple-700",
  termination: "bg-red-500/15 text-red-700",
  other: "bg-ink-faint/20 text-ink-muted",
};

function TypeBadge({ type }: { type: string | null }) {
  const label = type ?? "other";
  const colour = TYPE_COLOURS[label] ?? TYPE_COLOURS.other;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colour}`}
    >
      {label}
    </span>
  );
}

function formatDeadline(iso: string | null) {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      dateStyle: "medium",
    });
  } catch {
    return iso;
  }
}

function isOverdue(deadline: string | null) {
  if (!deadline) return false;
  return new Date(deadline) < new Date();
}

interface ObligationRowProps {
  obligation: Obligation;
  onResolve: (id: string) => void;
  resolving: boolean;
}

function ObligationRow({ obligation, onResolve, resolving }: ObligationRowProps) {
  const overdue = isOverdue(obligation.deadline) && !obligation.is_resolved;
  return (
    <tr
      className={`hover:bg-surface-card/50 transition-colors ${
        obligation.is_resolved ? "opacity-50" : ""
      }`}
    >
      <td className="px-4 py-3">
        <p
          className={`text-sm text-ink leading-snug ${
            obligation.is_resolved ? "line-through text-ink-muted" : ""
          }`}
        >
          {obligation.description}
        </p>
      </td>
      <td className="px-4 py-3">
        <TypeBadge type={obligation.obligation_type} />
      </td>
      <td className="px-4 py-3 whitespace-nowrap text-xs">
        {obligation.deadline ? (
          <span
            className={
              overdue ? "text-red-600 font-semibold" : "text-ink-muted"
            }
          >
            {formatDeadline(obligation.deadline)}
            {overdue && " ⚠ overdue"}
          </span>
        ) : (
          <span className="text-ink-faint">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-center">
        {obligation.is_resolved ? (
          <CheckCircle2 size={16} className="text-emerald-500 mx-auto" />
        ) : (
          <button
            onClick={() => onResolve(obligation.id)}
            disabled={resolving}
            title="Mark as resolved"
            className="p-1 rounded hover:bg-surface-card text-ink-muted hover:text-emerald-600 transition-colors mx-auto flex"
          >
            {resolving ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Circle size={14} />
            )}
          </button>
        )}
      </td>
    </tr>
  );
}

interface ObligationListProps {
  /** Scope to a specific document. If omitted, shows all tenant obligations. */
  docId: string;
}

export function ObligationList({ docId }: ObligationListProps) {
  const [offset, setOffset] = useState(0);
  const [includeResolved, setIncludeResolved] = useState(false);
  const queryClient = useQueryClient();

  const qKey = ["obligations", docId, offset, includeResolved];

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: qKey,
    queryFn: () => listDocumentObligations(docId, includeResolved),
  });

  const extractMut = useMutation({
    mutationFn: () => extractObligations(docId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["obligations", docId] });
    },
  });

  const resolveMut = useMutation({
    mutationFn: (id: string) => resolveObligation(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["obligations", docId] });
    },
  });

  const items: Obligation[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-2 text-sm text-ink-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={includeResolved}
            onChange={(e) => {
              setIncludeResolved(e.target.checked);
              setOffset(0);
            }}
            className="rounded border-ink-faint/40 accent-gold"
          />
          Show resolved
        </label>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="Refresh"
            className="p-1.5 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-card transition-colors"
          >
            {isFetching ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
          </button>
          <button
            onClick={() => extractMut.mutate()}
            disabled={extractMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-gold/90 hover:bg-gold px-3 py-1.5 text-xs font-medium text-white transition-colors disabled:opacity-60"
          >
            {extractMut.isPending ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Sparkles size={13} />
            )}
            Extract obligations
          </button>
        </div>
      </div>

      {/* Extraction error */}
      {extractMut.isError && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">
          <AlertCircle size={14} />
          <span>Extraction failed. Please try again.</span>
        </div>
      )}

      {/* Load error */}
      {isError && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">
          <AlertCircle size={14} />
          <span>Failed to load obligations.</span>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-10 text-ink-muted gap-2">
          <Loader2 size={17} className="animate-spin" />
          <span className="text-sm">Loading obligations…</span>
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
                    Obligation
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Type
                  </th>
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Deadline
                  </th>
                  <th className="px-4 py-2.5 text-center font-medium text-ink-muted w-16">
                    Done
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
                      No obligations found. Click &ldquo;Extract obligations&rdquo; to scan
                      this document.
                    </td>
                  </tr>
                ) : (
                  items.map((ob) => (
                    <ObligationRow
                      key={ob.id}
                      obligation={ob}
                      onResolve={(id) => resolveMut.mutate(id)}
                      resolving={
                        resolveMut.isPending &&
                        resolveMut.variables === ob.id
                      }
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between text-xs text-ink-muted">
              <span>
                {total} obligation{total !== 1 ? "s" : ""} · page {currentPage}{" "}
                of {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40 transition-colors"
                >
                  <ChevronLeft size={13} />
                </button>
                <button
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40 transition-colors"
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
