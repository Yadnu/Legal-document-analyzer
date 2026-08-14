/** Shared TypeScript types mirroring the FastAPI backend DTOs. */

export type DocumentStatus = "processing" | "ready" | "failed";

export interface DocumentSummary {
  id: string;
  title: string;
  status: DocumentStatus;
  created_at: string;
}

export interface DocumentResponse extends DocumentSummary {
  tenant_id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
}

export interface PresignedUploadResponse {
  document_id: string;
  upload_url: string;
  s3_key: string;
  expires_in: number;
}

export interface ViewUrlResponse {
  document_id: string;
  url: string;
  expires_in: number;
}

export interface CitationOut {
  document_id: string;
  chunk_id: string;
  section: string | null;
  quote: string;
}

export interface QueryRequest {
  question: string;
  document_id?: string;
  conversation_id?: string;
}

export interface QueryResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  not_found: boolean;
  citations: CitationOut[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  not_found?: boolean;
  citations?: CitationOut[];
}
