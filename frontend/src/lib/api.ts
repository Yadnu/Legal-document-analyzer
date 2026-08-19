/**
 * Client-side fetch helpers that call the Next.js BFF route handlers.
 * These never talk directly to FastAPI — auth is handled server-side.
 */
import type {
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

export async function getDocumentSummary(
  id: string
): Promise<DocumentSummaryCard> {
  return apiFetch<DocumentSummaryCard>(`/api/documents/${id}/summary`);
}

// ── Query ──────────────────────────────────────────────────────────────────

export async function askQuestion(body: QueryRequest): Promise<QueryResponse> {
  return apiFetch<QueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
