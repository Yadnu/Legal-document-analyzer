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

export interface QuotaResponse {
  doc_count: number;
  doc_quota: number;
  qa_used: number;
  qa_quota: number;
}

// ── Obligations ───────────────────────────────────────────────────────────

export type ObligationType =
  | "payment"
  | "notice"
  | "renewal"
  | "termination"
  | "other";

export interface Obligation {
  id: string;
  document_id: string;
  chunk_id: string | null;
  description: string;
  obligation_type: ObligationType | null;
  deadline: string | null;
  reminder_days_before: number;
  reminder_sent_at: string | null;
  is_resolved: boolean;
  assigned_to: string | null;
  created_at: string;
}

export type WorkspaceRole = "admin" | "editor" | "viewer";

export interface WorkspaceMember {
  user_id: string;
  email: string;
  full_name: string | null;
  role: WorkspaceRole;
  is_active: boolean;
  created_at: string;
}

export interface WorkspaceInvite {
  id: string;
  email: string;
  role: WorkspaceRole;
  status: string;
  invited_by: string;
  expires_at: string;
  created_at: string;
  invite_url?: string;
}

export interface WorkspaceSnapshot {
  name: string;
  slug: string;
  caller_role: WorkspaceRole;
  max_members: number;
  seat_count: number;
  members: WorkspaceMember[];
  invites: WorkspaceInvite[];
}

export interface InviteAccepted {
  tenant_id: string;
  workspace_name: string;
  role: WorkspaceRole;
}

export interface ObligationListResponse {
  items: Obligation[];
  total: number;
}
