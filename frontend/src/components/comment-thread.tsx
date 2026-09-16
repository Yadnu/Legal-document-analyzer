"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Send,
  Trash2,
} from "lucide-react";
import {
  createComment,
  deleteComment,
  listComments,
  patchComment,
} from "@/lib/api";
import type { CitationOut, ClauseComment } from "@/lib/types";

interface CommentThreadProps {
  documentId: string;
  citation: CitationOut;
  /** Clerk user_id of the current user so we know which comments they own. */
  currentUserId?: string;
}

// ---------------------------------------------------------------------------
// Single comment row
// ---------------------------------------------------------------------------

function CommentRow({
  comment,
  isOwn,
  onResolve,
  onDelete,
}: {
  comment: ClauseComment;
  isOwn: boolean;
  onResolve: (id: string, resolved: boolean) => void;
  onDelete: (id: string) => void;
}) {
  const [showMenu, setShowMenu] = useState(false);

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString(undefined, {
        dateStyle: "short",
        timeStyle: "short",
      });
    } catch {
      return iso;
    }
  }

  return (
    <div
      className={`group py-2.5 px-4 border-b border-surface-card last:border-0 ${
        comment.is_resolved ? "opacity-50" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        {/* User badge */}
        <div className="flex items-center gap-1.5 min-w-0">
          <div className="w-5 h-5 rounded-full bg-gold/20 flex items-center justify-center shrink-0">
            <span className="text-[9px] font-semibold text-gold uppercase">
              {comment.user_id.slice(-2)}
            </span>
          </div>
          <span className="text-[10px] text-ink-muted truncate">
            {formatDate(comment.created_at)}
            {comment.updated_at && (
              <span className="ml-1 italic opacity-60">edited</span>
            )}
          </span>
          {comment.is_resolved && (
            <CheckCircle2 size={10} className="text-status-ready shrink-0" />
          )}
        </div>

        {/* Actions menu (only for own comments) */}
        {isOwn && (
          <div className="relative shrink-0">
            <button
              onClick={() => setShowMenu((s) => !s)}
              className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-ink-muted hover:text-ink transition-all"
            >
              <MoreHorizontal size={12} />
            </button>
            {showMenu && (
              <div
                className="absolute right-0 top-5 z-20 min-w-[130px] rounded-lg border border-ink-faint/20 bg-surface shadow-md py-1"
                onBlur={() => setShowMenu(false)}
              >
                <button
                  onClick={() => {
                    onResolve(comment.id, !comment.is_resolved);
                    setShowMenu(false);
                  }}
                  className="w-full text-left px-3 py-1.5 text-xs text-ink hover:bg-surface-card transition-colors"
                >
                  {comment.is_resolved ? "Unresolve" : "Resolve"}
                </button>
                <button
                  onClick={() => {
                    onDelete(comment.id);
                    setShowMenu(false);
                  }}
                  className="w-full text-left px-3 py-1.5 text-xs text-status-red hover:bg-surface-card transition-colors flex items-center gap-1.5"
                >
                  <Trash2 size={10} />
                  Delete
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <p className="mt-1 text-xs text-ink leading-relaxed pl-6.5">
        {comment.body}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thread panel
// ---------------------------------------------------------------------------

export function CommentThread({
  documentId,
  citation,
  currentUserId,
}: CommentThreadProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const queryKey = ["comments", documentId, citation.chunk_id];

  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => listComments(documentId, citation.chunk_id),
    staleTime: 30_000,
    enabled: !!citation.chunk_id,
  });

  const postMutation = useMutation({
    mutationFn: (body: string) =>
      createComment(documentId, citation.chunk_id, body),
    onSuccess: () => {
      setDraft("");
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  const resolveMutation = useMutation({
    mutationFn: ({
      id,
      resolved,
    }: {
      id: string;
      resolved: boolean;
    }) => patchComment(id, { is_resolved: resolved }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteComment(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });

  const comments = data?.items ?? [];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    postMutation.mutate(trimmed);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Cmd/Ctrl+Enter submits
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  return (
    <div className="border-t border-surface-card">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-4 pt-3 pb-2">
        <MessageSquare size={12} className="text-gold" />
        <span className="text-[10px] font-semibold tracking-widest uppercase text-ink-muted">
          Comments
        </span>
        {comments.length > 0 && (
          <span className="text-[10px] text-ink-muted/40 ml-auto">
            {comments.filter((c) => !c.is_resolved).length} open
          </span>
        )}
      </div>

      {/* Comment list */}
      {isLoading && (
        <div className="px-4 pb-3 flex items-center gap-2 text-ink-muted/60 text-xs">
          <Loader2 size={11} className="animate-spin" />
          Loading…
        </div>
      )}
      {isError && (
        <div className="px-4 pb-2 flex items-center gap-1.5 text-status-red/70 text-xs">
          <AlertCircle size={11} />
          Could not load comments
        </div>
      )}
      {!isLoading && !isError && comments.length === 0 && (
        <p className="px-4 pb-2 text-xs text-ink-muted/40 italic">
          No comments yet — be the first.
        </p>
      )}
      {!isLoading && comments.map((c) => (
        <CommentRow
          key={c.id}
          comment={c}
          isOwn={c.user_id === currentUserId}
          onResolve={(id, resolved) =>
            resolveMutation.mutate({ id, resolved })
          }
          onDelete={(id) => deleteMutation.mutate(id)}
        />
      ))}

      {/* Compose box */}
      <form
        onSubmit={handleSubmit}
        className="px-4 pb-3 pt-1 flex flex-col gap-1.5"
      >
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Add a comment… (⌘↵ to send)"
          rows={2}
          className="w-full resize-none rounded-lg border border-ink-faint/30 bg-surface px-2.5 py-2 text-xs text-ink placeholder:text-ink-muted/50 focus:outline-none focus:ring-1 focus:ring-gold/60"
        />
        <div className="flex items-center justify-end">
          <button
            type="submit"
            disabled={!draft.trim() || postMutation.isPending}
            className="flex items-center gap-1.5 btn-primary py-1 px-3 text-xs disabled:opacity-50"
          >
            {postMutation.isPending ? (
              <Loader2 size={11} className="animate-spin" />
            ) : (
              <Send size={11} />
            )}
            Post
          </button>
        </div>
        {postMutation.isError && (
          <p className="text-[10px] text-status-red">
            Failed to post comment — please try again.
          </p>
        )}
      </form>
    </div>
  );
}
