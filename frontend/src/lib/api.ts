/**
 * Client-side fetch helpers that call the Next.js BFF route handlers.
 * These never talk directly to FastAPI — auth is handled server-side.
 */
import type {
  ChunkRefsResponse,
  DocumentResponse,
  DocumentSummary,
  DocumentSummaryCard,
  PresignedUploadResponse,
  QueryRequest,
  QueryResponse,
  ViewUrlResponse,
} from "./types";

async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Documents ──────────────────────────────────────────────────────────────

export async function listDocuments(): Promise<DocumentSummary[]> {
  return apiFetch<DocumentSummary[]>("/api/documents");
}

export async function getDocument(id: string): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`/api/documents/${id}`);
}

export async function getViewUrl(id: string): Promise<ViewUrlResponse> {
  return apiFetch<ViewUrlResponse>(`/api/documents/${id}/view-url`);
}

// ── Upload ─────────────────────────────────────────────────────────────────

export async function requestPresignedUpload(body: {
  filename: string;
  content_type: string;
  size_bytes: number;
}): Promise<PresignedUploadResponse> {
  return apiFetch<PresignedUploadResponse>("/api/upload/presign", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function putFileToS3(
  url: string,
  file: File
): Promise<void> {
  const res = await fetch(url, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type },
  });
  if (!res.ok) throw new Error(`S3 upload failed: ${res.status}`);
}

export async function confirmUpload(
  documentId: string
): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`/api/upload/confirm/${documentId}`, {
    method: "POST",
  });
}

export async function getChunkRefs(
  docId: string,
  chunkId: string
): Promise<ChunkRefsResponse> {
  return apiFetch<ChunkRefsResponse>(
    `/api/documents/${docId}/chunks/${chunkId}/refs`
  );
}

export async function getDocumentSummary(
  id: string
): Promise<DocumentSummaryCard> {
  return apiFetch<DocumentSummaryCard>(`/api/documents/${id}/summary`);
}

export async function listConversations(): Promise<import("./types").ConversationSummary[]> {
  return apiFetch("/api/conversations");
}

export async function getAuditLog(params?: {
  action?: string;
  limit?: number;
  offset?: number;
}): Promise<import("./types").AuditLogResponse> {
  const qs = new URLSearchParams();
  if (params?.action) qs.set("action", params.action);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch(`/api/audit-log${query}`);
}

// ── Comments ───────────────────────────────────────────────────────────────

export async function listComments(
  docId: string,
  chunkId: string
): Promise<import("./types").CommentListResponse> {
  return apiFetch(
    `/api/documents/${docId}/chunks/${chunkId}/comments`
  );
}

export async function createComment(
  docId: string,
  chunkId: string,
  body: string
): Promise<import("./types").ClauseComment> {
  return apiFetch(
    `/api/documents/${docId}/chunks/${chunkId}/comments`,
    { method: "POST", body: JSON.stringify({ body }) }
  );
}

export async function patchComment(
  commentId: string,
  patch: { body?: string; is_resolved?: boolean }
): Promise<import("./types").ClauseComment> {
  return apiFetch(`/api/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteComment(commentId: string): Promise<void> {
  const res = await fetch(`/api/comments/${commentId}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
}

// ── Query ──────────────────────────────────────────────────────────────────

export async function askQuestion(body: QueryRequest): Promise<QueryResponse> {
  return apiFetch<QueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
