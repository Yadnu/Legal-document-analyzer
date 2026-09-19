"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { listTenantObligations } from "@/lib/api";
import type { Obligation } from "@/lib/types";

const PAGE_SIZE = 50;

const TYPE_COLOURS: Record<string, string> = {
  payment: "bg-emerald-500/15 text-emerald-700",
  notice: "bg-blue-500/15 text-blue-700",
  renewal: "bg-purple-500/15 text-purple-700",
  termination: "bg-red-500/15 text-red-700",
  other: "bg-ink-faint/20 text-ink-muted",
};

const TYPES = ["", "payment", "notice", "renewal", "termination", "other"];

function TypeBadge({ type }: { type: string | null }) {
  const label = type ?? "other";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        TYPE_COLOURS[label] ?? TYPE_COLOURS.other
      }`}
    >
      {label}
    </span>
  );
}

function formatDeadline(iso: string | null) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
  } catch {
    return iso;
  }
}

function isOverdue(ob: Obligation) {
  return !!ob.deadline && !ob.is_resolved && new Date(ob.deadline) < new Date();
}

export function ObligationsDashboard() {
  const [offset, setOffset] = useState(0);
  const [typeFilter, setTypeFilter] = useState("");
  const [includeResolved, setIncludeResolved] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["obligations-all", offset, typeFilter, includeResolved],
    queryFn: () =>
      listTenantObligations({
        include_resolved: includeResolved,
        obligation_type: typeFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const items: Obligation[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-5">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter(e.target.value);
            setOffset(0);
          }}
          className="rounded-lg border border-ink-faint/30 bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-gold/60"
        >
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t || "All types"}
            </option>
          ))}
        </select>

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
          Include resolved
        </label>

        <span className="ml-auto text-xs text-ink-muted">
          {total} obligation{total !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Error */}
      {isError && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">
          <AlertCircle size={14} />
          Failed to load obligations.
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-12 text-ink-muted gap-2">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Loading…</span>
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
                  <th className="px-4 py-2.5 text-left font-medium text-ink-muted">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-faint/10">
                {items.length === 0 ? (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-4 py-10 text-center text-sm text-ink-muted"
                    >
                      No obligations found. Open a document and click
                      &ldquo;Extract obligations&rdquo; to get started.
                    </td>
                  </tr>
                ) : (
                  items.map((ob) => (
                    <tr
                      key={ob.id}
                      className={`hover:bg-surface-card/50 transition-colors ${
                        ob.is_resolved ? "opacity-50" : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <p
                          className={`text-sm text-ink leading-snug ${
                            ob.is_resolved
                              ? "line-through text-ink-muted"
                              : ""
                          }`}
                        >
                          {ob.description}
                        </p>
                        <p className="text-xs text-ink-faint font-mono mt-0.5 truncate max-w-[240px]">
                          doc: {ob.document_id.slice(0, 8)}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <TypeBadge type={ob.obligation_type} />
                      </td>
                      <td
                        className={`px-4 py-3 whitespace-nowrap text-xs ${
                          isOverdue(ob)
                            ? "text-red-600 font-semibold"
                            : "text-ink-muted"
                        }`}
                      >
                        {formatDeadline(ob.deadline)}
                        {isOverdue(ob) && " ⚠"}
                      </td>
                      <td className="px-4 py-3">
                        {ob.is_resolved ? (
                          <span className="text-xs text-emerald-600 font-medium">
                            Resolved
                          </span>
                        ) : (
                          <span className="text-xs text-ink-muted">Open</span>
                        )}
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
                Page {currentPage} of {totalPages}
              </span>
              <div className="flex items-center gap-1">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40"
                >
                  <ChevronLeft size={13} />
                </button>
                <button
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="p-1 rounded hover:bg-surface-card disabled:opacity-40"
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
