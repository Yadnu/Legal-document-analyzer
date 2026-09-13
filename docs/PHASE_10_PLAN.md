# Phase 10 — Platform Layer

> **Done when:** reminders fire, teammates can collaborate, actions are audited,
> and the eval harness reports retrieval and grounding quality.

Phase 10 is the largest phase. It is broken into **6 independent sub-phases**
that can be built and shipped one at a time, each with its own done criteria.

---

## Sub-phase map

| ID | Name | Effort | Value |
|---|---|---|---|
| **10A** | Obligation tracker + extraction | Medium | ⭐⭐⭐ |
| **10B** | Deadline reminder worker | Small | ⭐⭐⭐ |
| **10C** | Audit log | Small | ⭐⭐ |
| **10D** | Clause-level comments (collaboration) | Medium | ⭐⭐ |
| **10E** | Roles + quotas | Medium | ⭐⭐⭐ |
| **10F** | RAG evaluation harness | Medium | ⭐⭐ |

Pre-conditions already met:
- `Obligation` SQLModel exists (Phase 2 scaffold).
- `AuditEvent` SQLModel exists (Phase 2 scaffold).
- Worker process, SQS, Bedrock all wired.

---

## 10A — Obligation Tracker + Extraction

### What it does
When a document is ready, a single Bedrock call extracts obligations and
deadlines from the summary card chunks and stores them in the `obligations`
table. Users can view, edit, mark resolved, and filter by type or deadline.

### Backend tasks

**New migration:** `0003_obligations_index.py`
- Add index on `(tenant_id, deadline)` for fast upcoming-deadline queries.

**New service:** `backend/app/services/obligation_service.py`
```python
async def extract_for_document(session, tenant_id, document_id) -> list[Obligation]
async def list_obligations(session, tenant_id, *, document_id, resolved) -> list[Obligation]
async def update_obligation(session, tenant_id, obligation_id, patch) -> Obligation
async def mark_resolved(session, tenant_id, obligation_id) -> Obligation
```

**New schemas:** `backend/app/schemas/obligation.py`
- `ObligationOut`, `ObligationPatch`, `ObligationListResponse`

**New endpoints** (new router `backend/app/api/v1/obligations.py`):
```
POST   /documents/{doc_id}/obligations/extract  Trigger extraction
GET    /documents/{doc_id}/obligations          List for a document
GET    /obligations                             List all for tenant (filterable)
PATCH  /obligations/{id}                        Edit description/deadline/assigned_to
POST   /obligations/{id}/resolve                Mark resolved
```

**Extraction prompt:** ask Bedrock for obligations in JSON array:
```json
[{
  "description": "...",
  "obligation_type": "payment|notice|renewal|termination|other",
  "deadline": "YYYY-MM-DD or null",
  "reminder_days_before": 7,
  "chunk_id": "..."
}]
```

### Frontend tasks
- `ObligationList` component per document (shown in doc sidebar)
- `WorkspaceObligations` page (`/workspace/obligations`) — all upcoming deadlines
- Edit modal: change deadline, assignee, mark resolved

### Done criteria
- [ ] Extract produces typed obligations with deadlines from real docs
- [ ] CRUD endpoints work and are tenant-scoped
- [ ] UI shows upcoming deadlines sorted by date

---

## 10B — Deadline Reminder Worker

### What it does
A scheduled job (runs every hour via APScheduler inside the worker process)
queries obligations with `deadline BETWEEN now() AND now() + reminder_days_before`
and `reminder_sent_at IS NULL`, sends an email (SES or stub), and sets
`reminder_sent_at`.

### Backend tasks

**Edit:** `backend/app/worker/scheduler.py` (new file)
- APScheduler `AsyncIOScheduler` with one job: `send_due_reminders`.

**New service:** `backend/app/services/reminder_service.py`
```python
async def send_due_reminders(session: AsyncSession) -> int
    """Find due obligations, send emails, stamp reminder_sent_at. Returns count."""
```

**Infra:** `backend/app/infra/ses.py`
- `send_reminder_email(to, obligation)` — boto3 SES or log-only stub when
  `SES_ENABLED=false` (default in dev/CI).

**Config:** add `ses_enabled`, `ses_from_address`, `reminder_check_interval_minutes`
to `settings`.

### Done criteria
- [ ] Scheduler fires every N minutes
- [ ] Obligations within the reminder window get an email (or log entry in dev)
- [ ] `reminder_sent_at` is stamped; no duplicate sends

---

## 10C — Audit Log

### What it does
Every significant action (upload, Q&A, obligation resolve, settings change,
invite) appends a row to `audit_events`. Admins can query the last 500 events.

### Backend tasks

**New service:** `backend/app/services/audit_service.py`
```python
async def log(session, tenant_id, user_id, action, *, resource_type, resource_id, metadata)
```

**Wire into existing services** (one `await audit_service.log(...)` call each):
- `upload_service.confirm_upload` → `document.upload`
- `qa_service.ask` → `qa.ask`
- `obligation_service.mark_resolved` → `obligation.resolved`

**New endpoint:**
```
GET /audit-log?limit=100&action=<filter>
```
Returns `list[AuditEventOut]`; admin-only (checked against Clerk org role).

### Frontend tasks
- Settings page (`/workspace/settings`) with an **Audit log** tab
- Table: timestamp, user, action, resource

### Done criteria
- [ ] Upload, Q&A, and obligation resolve each produce an audit row
- [ ] `GET /audit-log` returns tenant-scoped events only
- [ ] UI renders the audit table

---

## 10D — Clause-Level Comments (Collaboration)

### What it does
Any user in the org can leave a comment on a specific chunk (clause).
Comments appear as annotations in the PDF viewer when that chunk is active.

### Backend tasks

**New migration:** `0004_comments.py`
```sql
CREATE TABLE clause_comments (
    id uuid PRIMARY KEY,
    tenant_id text NOT NULL,
    document_id uuid REFERENCES documents(id),
    chunk_id uuid REFERENCES chunks(id),
    user_id text NOT NULL,
    body text NOT NULL,
    resolved boolean DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- RLS policy
```

**New model:** `backend/app/models/clause_comment.py`

**New endpoints:**
```
GET    /documents/{doc_id}/chunks/{chunk_id}/comments
POST   /documents/{doc_id}/chunks/{chunk_id}/comments
PATCH  /comments/{id}     (edit body or resolve)
DELETE /comments/{id}     (author or admin only)
```

### Frontend tasks
- Comment thread panel below `CrossRefPanel` in doc layout
- Inline "Add comment" button in `PdfViewer` when a chunk is active
- Resolved comments shown greyed-out

### Done criteria
- [ ] Comments are tenant-scoped and chunk-linked
- [ ] UI shows the thread for the active citation
- [ ] Any org member can comment; only author/admin can delete

---

## 10E — Roles + Quotas

### What it does
Roles: `admin`, `editor`, `viewer` stored as Clerk org metadata (or a local
`org_member_roles` table). Certain endpoints (audit log, delete document) require
`admin`. Quotas: per-tenant limits on document count and monthly Q&A calls.

### Backend tasks

**New dependency:** `get_current_role` — reads the Clerk JWT `org_role` claim.

**Role guards** added to:
- `GET /audit-log` → admin only
- `DELETE /documents/{id}` → admin only (new endpoint)
- `POST /documents/{doc_id}/obligations/extract` → editor+

**New migration:** `0005_quotas.py`
```sql
ALTER TABLE organizations ADD COLUMN doc_quota integer DEFAULT 50;
ALTER TABLE organizations ADD COLUMN monthly_qa_quota integer DEFAULT 500;
ALTER TABLE organizations ADD COLUMN monthly_qa_used integer DEFAULT 0;
```

**Quota enforcement in:**
- `upload_service.request_upload` → check `doc_count < doc_quota`
- `qa_service.ask` → check + increment `monthly_qa_used`

**Scheduled reset:** first of month sets `monthly_qa_used = 0` (APScheduler job).

### Frontend tasks
- Quota usage bar in workspace header (`n / 50 documents`)
- 402 / 429 error handling in upload + chat

### Done criteria
- [ ] `viewer` cannot upload or comment
- [ ] Upload is rejected with 429 when over quota
- [ ] Q&A is rejected when monthly Q&A quota exhausted

---

## 10F — RAG Evaluation Harness

### What it does
A CLI tool (`backend/scripts/eval_rag.py`) runs a golden Q&A dataset through
the live retrieval+generation stack and reports:
- **Retrieval recall** — were the correct chunks retrieved?
- **Faithfulness** — does the answer only use the retrieved chunks? (LLM-as-judge)
- **Answer relevance** — does the answer address the question?

### Tasks

**New file:** `backend/data/golden_qa.json`
```json
[{
  "question": "...",
  "expected_chunk_sections": ["2.1", "3"],
  "expected_answer_keywords": ["30 days", "payment"]
}]
```

**New script:** `backend/scripts/eval_rag.py`
- Reads golden set, runs `retrieve()` + `generate_answer()` for each
- Computes: chunk recall@k, faithfulness score (Bedrock judge), latency
- Outputs JSON report + human-readable table

**CI job:** `eval` workflow (manual trigger only, not on every push)

### Done criteria
- [ ] Script runs end-to-end without errors against a seeded test DB
- [ ] Reports recall@5 and faithfulness score per question
- [ ] JSON report is saved as a CI artifact

---

## Recommended build order

```
10A → 10C → 10B → 10E → 10D → 10F
```

Rationale: obligations first (highest user value), audit log is cheap and
needed by 10E, reminders build on obligations, roles/quotas protect everything,
comments are pure feature, eval harness is a developer tool last.

---

## File map summary

```
backend/alembic/versions/0003_obligations_index.py   10A
backend/alembic/versions/0004_comments.py            10D
backend/alembic/versions/0005_quotas.py              10E
backend/app/models/clause_comment.py                 10D
backend/app/schemas/obligation.py                    10A
backend/app/services/obligation_service.py           10A
backend/app/services/reminder_service.py             10B
backend/app/services/audit_service.py                10C
backend/app/infra/ses.py                             10B
backend/app/worker/scheduler.py                      10B
backend/app/api/v1/obligations.py                    10A
backend/app/api/v1/audit.py                          10C
backend/app/api/v1/comments.py                       10D
backend/app/core/deps.py                  MOD (10E — get_current_role)
backend/scripts/eval_rag.py                          10F
backend/data/golden_qa.json                          10F
frontend/src/app/workspace/obligations/page.tsx      10A
frontend/src/components/obligation-list.tsx          10A
frontend/src/app/workspace/settings/page.tsx         10C
frontend/src/components/comment-thread.tsx           10D
```
