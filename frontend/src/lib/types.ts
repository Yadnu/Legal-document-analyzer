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
  document_title?: string | null;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  message_count: number;
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

export interface ResolvedRef {
  raw: string;
  normalised: string;
  target_chunk_id: string | null;
  target_section: string | null;
  target_heading: string | null;
  target_page: number | null;
  target_content: string | null;
}

export interface ChunkRefsResponse {
  chunk_id: string;
  document_id: string;
  refs: ResolvedRef[];
}

export interface SummaryField {
  value: string | null;
  chunk_id: string | null;
  section: string | null;
  quote: string | null;
}

export interface DocumentSummaryCard {
  document_id: string;
  parties: SummaryField;
  effective_date: SummaryField;
  term_length: SummaryField;
  payment_terms: SummaryField;
  termination_rights: SummaryField;
  liability_caps: SummaryField;
  governing_law: SummaryField;
  extracted_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  not_found?: boolean;
  citations?: CitationOut[];
}

export interface AuditEvent {
  id: string;
  user_id: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AuditLogResponse {
  items: AuditEvent[];
  total: number;
}

export interface ClauseComment {
  id: string;
  document_id: string;
  chunk_id: string;
  user_id: string;
  body: string;
  is_resolved: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface CommentListResponse {
  items: ClauseComment[];
}
