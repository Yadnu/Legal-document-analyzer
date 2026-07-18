# Legal Document Navigator — Build Plan

## Role and working rules

Senior full-stack and AI engineer. Build end to end following this plan exactly. Prefer small,
focused, well-tested changes. Do not skip phases or add unrequested features. When something is
ambiguous, follow patterns already in the codebase and ask before deviating.

## Product

A multi-tenant, AI-powered platform where users upload their own legal documents (contracts,
leases, policies) and ask questions answered with grounded, clause-level citations. Document
COMPREHENSION tool only — never legal advice. Keep a visible disclaimer in the UI.

## Tech stack (use exactly these)

- Frontend: Next.js (App Router), TypeScript (strict), Tailwind, shadcn/ui, TanStack Query,
  react-pdf or PDF.js for the document viewer.
- Backend: FastAPI (async), Uvicorn, Pydantic v2, SQLModel, Alembic, asyncpg.
- Auth: Clerk (Organizations feature as the tenant primitive); JWTs verified server-side in
  FastAPI against Clerk JWKS.
- Database: PostgreSQL with pgvector (HNSW). Amazon RDS in deployment.
- Storage: Amazon S3, direct browser upload via presigned URLs.
- Queue: Amazon SQS with a dead-letter queue, for the async ingestion worker.
- AI: Claude via Amazon Bedrock (primary generation); Groq Llama 3.3 70B (cheap supporting
  steps); embeddings via Bedrock or Voyage voyage-law-2; reranking via Cohere Rerank or local
  bge-reranker; parsing via LlamaParse or unstructured, with Amazon Textract for scanned docs.
- Infra: ECS on Fargate (one API service, one worker), Amplify or Vercel for frontend,
  Terraform or AWS Copilot for IaC.

## Architecture boundaries

- Next.js is a thin frontend and BFF: UI, Clerk sessions, presigned upload requests, simple
  reads. No business logic; never writes to the database directly.
- FastAPI is the single backend brain: all ingestion, retrieval, AI calls, and business logic.
- Postgres is the single source of truth. FastAPI owns the schema and all writes.
- Heavy work (parse, chunk, embed) runs only in the async worker, never inline in a request.

## Hard rules

### Multi-tenancy (critical)
- Every domain table has a tenant_id column.
- Derive the tenant ONLY from the verified Clerk JWT org claim. Never from a request body or
  query parameter.
- Provide a get_current_tenant dependency and apply it to every protected route.
- Filter every query by tenant_id at the service and repository layers.
- Enforce Postgres Row-Level Security: set a per-connection tenant session variable and write
  RLS policies so a query can never read another tenant's rows.
- Include a test proving tenant A cannot read tenant B's data.

### Security
- Verify Clerk JWTs against cached JWKS on every request.
- Lock CORS to the known frontend origin only.
- Presigned S3 uploads; validate content type and size before issuing the URL.
- Per-tenant rate limits and quotas. Validate all input (Pydantic and Zod); reject unknown fields.
- Least-privilege IAM per service. No secrets in the repo. Secrets from AWS Secrets Manager.
- Treat all document text as untrusted data, never as instructions (prompt-injection safe).

### Backend layering (strict)
- routers (thin, HTTP only) -> services (business logic) -> repositories (data access).
- Separate Pydantic DTOs from SQLModel table models. Never return a table model from an endpoint.
- Use FastAPI Depends for db session, current user, current tenant, and settings.
- Async everywhere. Config via pydantic-settings; no hardcoded secrets or model names.
- Central error handling: custom exceptions, registered handlers, one consistent error shape.
- Structured JSON logging with a request id; never log secrets or full document text.
- Alembic for all schema changes; never auto-create tables in production.

### Frontend
- TypeScript strict, no any. Server Components by default; Client Components only when needed.
- TanStack Query for all server state; no ad hoc fetching in useEffect. Zod for all forms.
- Uploads go directly to S3 via a presigned URL from the backend. No secrets in client code.

### RAG pipeline
- Chunking: structure-aware, clause-level, isolated unit-tested module. Preserve section
  number, heading, page, and cross-references as metadata. No naive fixed-size chunking.
- Embeddings: one embedding function and version for BOTH documents and queries; store model
  name and version with each vector. Never mix models across documents and queries.
- Retrieval: hybrid dense (pgvector) plus sparse (BM25/tsvector), fused with RRF, then
  reranked. Always tenant-scoped.
- Generation: only reranked, tenant-scoped clauses to Claude via Bedrock with strict grounding
  prompt. Every claim cites a clause; if none supports it, respond "not found in your
  documents." Never fabricate a citation. Return structured citations (document id, chunk id,
  section) for the viewer to highlight.
- Ingestion: idempotent, keyed by document id, retryable. Failures go to DLQ and set status
  to failed with a reason. Status flow: processing -> ready -> failed.

## Phases

### Phase 0 — Scaffolding
Monorepo structure, FastAPI app factory, Next.js app, docker-compose (Postgres pgvector +
LocalStack), lint/format/pre-commit, typed settings, CI.

**Done when:** both apps start with one command, health checks pass, CI runs green.

### Phase 1 — Auth and tenant context
Clerk in frontend; verify JWT vs JWKS in FastAPI; get_current_user and get_current_tenant
dependencies; protected GET /me.

**Done when:** authenticated request returns user and tenant; unauthenticated is rejected.

### Phase 2 — Data model and RLS
Enable pgvector; SQLModel models (Organization, User, Document, Chunk, Conversation, Message,
Obligation, AuditEvent), each with tenant_id; Alembic migrations; RLS policies and the tenant
session variable.

**Done when:** migrations apply cleanly and a test proves RLS blocks cross-tenant reads.

### Phase 3 — Upload pipeline
Presigned S3 upload endpoint (validate type and size); create document record; enqueue SQS job;
worker consumes and updates status; dead-letter queue.

**Done when:** upload creates a processing document and the worker transitions status.

### Phase 4 — Ingestion
Worker parses (LlamaParse/unstructured, Textract fallback), runs structure-aware clause
chunking with section metadata, embeds with the single embedding function, stores vectors plus
tsvector. Idempotent and retryable.

**Done when:** clause-level chunks have correct metadata, status reaches ready, rerun makes no
duplicates.

### Phase 5 — Grounded Q&A (MVP core)
Retrieval service (dense plus sparse, RRF, rerank, tenant-scoped); generation via Bedrock
Claude with strict grounding and structured citations; query endpoint; cite-or-not-found
behavior.

**Done when:** a question returns a grounded, cited answer; an unanswerable one returns "not
found in your documents."

### Phase 6 — Chat UI and viewer
Workspace and document list, chat interface, document viewer that highlights a cited passage on
click, plain-English explanation of a selected clause.

**Done when:** a user can upload, ask, read the answer, and click a citation to see the
highlighted source.

### Phase 7 — Structured clause extraction
Summary card (parties, effective date, term length, payment terms, termination rights,
liability caps, governing law), grounded and linked to clauses.

**Done when:** opening a document shows an accurate card, each field linking to its clause.

### Phase 8 — Cross-reference resolution
Detect and resolve references like "as defined in Section 2" or "subject to Exhibit B" using
section metadata, and surface the referenced text.

**Done when:** a clause with a reference exposes the resolved target text on demand.

### Phase 9 — Multi-document workspace
Retrieval spans all documents in a tenant; workspace management; questions like "which of my
contracts auto-renew."

**Done when:** a cross-document question cites the right document and clause for each point.

### Phase 10 — Platform layer
Obligation and deadline tracker with reminders (scheduled worker jobs), collaboration (shared
workspaces, invites, clause-level comments), roles, quotas, and an audit log, plus a RAG
evaluation harness with a faithfulness check.

**Done when:** reminders fire, teammates can collaborate, actions are audited, and the eval
harness reports retrieval and grounding quality.
