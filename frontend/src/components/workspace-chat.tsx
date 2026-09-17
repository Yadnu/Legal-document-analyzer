"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Send,
  Loader2,
  Globe,
  BookOpen,
  AlertCircle,
} from "lucide-react";
import { askQuestion } from "@/lib/api";
import type { ChatMessage, CitationOut } from "@/lib/types";

function CrossDocCitationChip({
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
  const label = [
    citation.document_title ?? `Doc ${index + 1}`,
    citation.section ? `§${citation.section}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      onClick={() => onClick(citation)}
      title={citation.quote}
      className={`citation-chip ${isActive ? "citation-chip-active" : ""}`}
    >
      <BookOpen size={10} />
      {label}
    </button>
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
  const isUser = msg.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "bg-gold/15 text-ink rounded-tr-sm"
            : "bg-surface-card border border-ink-faint/20 text-ink rounded-tl-sm"
        }`}
      >
        {msg.not_found ? (
          <span className="flex items-center gap-1.5 text-ink-muted/70 italic">
            <AlertCircle size={13} />
            Not found in your documents
          </span>
        ) : (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        )}

        {msg.citations && msg.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {msg.citations.map((c, i) => (
              <CrossDocCitationChip
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
    </div>
  );
}

export function WorkspaceChat() {
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [activeCitation, setActiveCitation] = useState<CitationOut | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const query = useMutation({
    mutationFn: askQuestion,
    onSuccess(data) {
      setConversationId(data.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: data.message_id,
          role: "assistant",
          content: data.answer,
          not_found: data.not_found,
          citations: data.citations,
        },
      ]);
      setTimeout(
        () => bottomRef.current?.scrollIntoView({ behavior: "smooth" }),
        50
      );
    },
    onError(err: Error) {
      const isQuota = err.message.startsWith("429");
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: isQuota
            ? "Monthly Q&A quota reached. Your quota resets on the 1st of next month."
            : "Something went wrong — please try again.",
          not_found: true,
        },
      ]);
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || query.isPending) return;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: text },
    ]);
    // No document_id → cross-document query
    query.mutate({
      question: text,
      conversation_id: conversationId,
    });
    setTimeout(
      () => bottomRef.current?.scrollIntoView({ behavior: "smooth" }),
      50
    );
  }

  function handleCitationClick(citation: CitationOut) {
    setActiveCitation((prev) =>
      prev?.chunk_id === citation.chunk_id ? null : citation
    );
    // Navigate to the document with the cited chunk pre-highlighted
    const params = new URLSearchParams({
      chunk: citation.chunk_id,
      quote: citation.quote ?? "",
    });
    router.push(`/workspace/${citation.document_id}?${params.toString()}`);
  }

  return (
    <div className="flex flex-col h-full bg-surface border border-surface-card rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-ink-faint/20 shrink-0">
        <div className="flex items-center gap-2">
          <Globe size={15} className="text-gold" />
          <h3 className="font-display text-base text-ink">
            Ask across all documents
          </h3>
        </div>
        <p className="text-xs text-ink-muted mt-0.5 ml-5">
          Questions span your entire workspace — each answer cites its source document.
        </p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4 min-h-0">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <div className="w-10 h-10 rounded-full bg-gold/10 border border-gold/20 flex items-center justify-center text-gold">
              <Globe size={18} />
            </div>
            <p className="text-ink-muted text-sm max-w-xs">
              Try &ldquo;Which contracts auto-renew?&rdquo; or &ldquo;Compare the payment
              terms across my documents.&rdquo;
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
          placeholder="Ask across all your documents…"
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
