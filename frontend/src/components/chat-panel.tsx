"use client";

import { useState, useRef, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { Send, Loader2, BookOpen, AlertCircle } from "lucide-react";
import { askQuestion } from "@/lib/api";
import type { ChatMessage, CitationOut, QueryResponse } from "@/lib/types";

function CitationChip({
  citation,
  index,
  isActive,
  onClick,
}: {
  citation: CitationOut;
  index: number;
  isActive: boolean;
  onClick: (c: CitationOut) => void;
}) {
  return (
    <button
      onClick={() => onClick(citation)}
      title={citation.quote}
      className={`citation-chip ${isActive ? "citation-chip-active" : ""}`}
    >
      <BookOpen size={10} />
      {citation.section ? `§${citation.section}` : `[${index + 1}]`}
    </button>
  );
}

function AssistantMessage({
  msg,
  activeCitation,
  onCitationClick,
}: {
  msg: ChatMessage;
  activeCitation: CitationOut | null;
  onCitationClick: (c: CitationOut) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      {msg.not_found ? (
        <div className="flex items-start gap-2 text-ink-muted text-sm">
          <AlertCircle size={14} className="mt-0.5 shrink-0 text-status-failed/70" />
          <span className="italic">{msg.content}</span>
        </div>
      ) : (
        <p className="text-sm text-ink leading-relaxed whitespace-pre-wrap">
          {msg.content}
        </p>
      )}

      {msg.citations && msg.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {msg.citations.map((c, i) => (
            <CitationChip
              key={c.chunk_id}
              citation={c}
              index={i}
              isActive={activeCitation?.chunk_id === c.chunk_id}
              onClick={onCitationClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MessageBubble({
  msg,
  activeCitation,
  onCitationClick,
}: {
  msg: ChatMessage;
  activeCitation: CitationOut | null;
  onCitationClick: (c: CitationOut) => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-xl rounded-tr-sm bg-gold/10 border border-gold/20 px-3.5 py-2.5 text-sm text-ink">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] rounded-xl rounded-tl-sm bg-surface-card border border-ink-faint/20 px-3.5 py-2.5">
        <AssistantMessage
          msg={msg}
          activeCitation={activeCitation}
          onCitationClick={onCitationClick}
        />
      </div>
    </div>
  );
}

interface ChatPanelProps {
  documentId: string;
  onCitationClick: (citation: CitationOut) => void;
  pendingQuestion?: string | null;
  onQuestionConsumed?: () => void;
}

export function ChatPanel({
  documentId,
  onCitationClick,
  pendingQuestion,
  onQuestionConsumed,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [activeCitation, setActiveCitation] = useState<CitationOut | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const query = useMutation({
    mutationFn: (question: string) =>
      askQuestion({ question, document_id: documentId, conversation_id: conversationId }),
    onSuccess: (res: QueryResponse) => {
      setConversationId(res.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: res.message_id,
          role: "assistant",
          content: res.answer,
          not_found: res.not_found,
          citations: res.citations,
        },
      ]);
    },
    onError: (err: Error) => {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: `Error: ${err.message}`,
          not_found: false,
          citations: [],
        },
      ]);
    },
  });

  // Auto-submit questions injected from the PDF viewer ("Explain clause")
  useEffect(() => {
    if (!pendingQuestion || query.isPending) return;
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: pendingQuestion },
    ]);
    query.mutate(pendingQuestion);
    onQuestionConsumed?.();
    // query.mutate and onQuestionConsumed are stable — omitting from deps intentionally
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion]);

  function handleCitationClick(c: CitationOut) {
    setActiveCitation((prev) => (prev?.chunk_id === c.chunk_id ? null : c));
    onCitationClick(c);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || query.isPending) return;

    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: q },
    ]);
    query.mutate(q);
  }

  return (
    <div className="flex flex-col h-full bg-surface border-l border-ink-faint/20">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-ink-faint/20 shrink-0">
        <h3 className="font-display text-base text-ink">Ask a question</h3>
        <p className="text-xs text-ink-muted mt-0.5">
          Answers cite the exact clause from this document.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="w-10 h-10 rounded-full bg-gold/10 border border-gold/20 flex items-center justify-center text-gold">
              <BookOpen size={18} />
            </div>
            <p className="text-ink-muted text-sm max-w-xs">
              Ask anything about this document — &ldquo;What are the termination
              conditions?&rdquo; or &ldquo;Who are the parties?&rdquo;
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            activeCitation={activeCitation}
            onCitationClick={handleCitationClick}
          />
        ))}

        {query.isPending && (
          <div className="flex justify-start">
            <div className="rounded-xl rounded-tl-sm bg-surface-card border border-ink-faint/20 px-3.5 py-2.5">
              <Loader2 size={14} className="animate-spin text-gold" />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="shrink-0 border-t border-ink-faint/20 p-3 flex items-end gap-2"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e);
            }
          }}
          placeholder="Ask about this document…"
          rows={2}
          className="flex-1 resize-none rounded-lg bg-surface-card border border-ink-faint/20 px-3 py-2
                     text-sm text-ink placeholder-ink-muted font-sans
                     focus:outline-none focus:border-gold/50 focus:ring-1 focus:ring-gold/30
                     transition-colors"
        />
        <button
          type="submit"
          disabled={!input.trim() || query.isPending}
          className="btn-primary shrink-0 px-3 py-2"
        >
          {query.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Send size={16} />
          )}
        </button>
      </form>
    </div>
  );
}
