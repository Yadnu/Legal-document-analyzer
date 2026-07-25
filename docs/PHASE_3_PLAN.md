# Phase 3 — Upload Pipeline

> **Goal:** A tenant user requests a presigned S3 URL, uploads a file directly from the
> browser, and the backend creates a `Document` record (status `processing`) and enqueues
> an SQS job. A worker process picks up the job and transitions the document to `ready` or
> `failed`. A dead-letter queue (DLQ) captures permanently-failing jobs.
>
> **Done when:** uploading a file creates a `processing` document, the worker picks it up
> and transitions status, and a test covers the full status flow.

---

## Pre-conditions (already done)

- Phase 2 complete: `documents` table exists with RLS, Alembic migration applied.
- `Document` SQLModel and `DocumentStatus` constants in `app/models/document.py`.
- `get_current_tenant` / `get_current_user` dependencies working.
- S3 bucket and SQS queue exist locally via LocalStack (docker-compose).
- Settings already have `aws_*`, `s3_bucket_name` fields in `app/core/config.py`.

---

## Task list

### T1 — Extend Settings for SQS

**File:** `backend/app/core/config.py`

Add new settings fields (all read from env; no hardcoded values):

```
sqs_queue_url: str = ""
sqs_dlq_url: str = ""
upload_max_size_bytes: int = 52_428_800   # 50 MB
upload_allowed_content_types: list[str] = ["application/pdf"]
presigned_url_expires_seconds: int = 300
```

Update `backend/.env.example` with matching entries and example LocalStack values.

---

### T2 — AWS client helpers

**New file:** `backend/app/infra/aws.py`

- Single `get_s3_client()` and `get_sqs_client()` factory functions using `aioboto3`
  (or `boto3` wrapped in `asyncio.to_thread` if aioboto3 is unavailable).
- Read credentials and `aws_endpoint_url` from `settings`; the endpoint override
  makes LocalStack transparent in development.
- No hardcoded region, endpoint, or credentials anywhere.

**Install:** add `aioboto3` (or `boto3`) to `pyproject.toml` dependencies.

---

### T3 — Document repository

**New file:** `backend/app/repositories/document_repo.py`

Async functions (all accept `AsyncSession` + `tenant_id`):

| Function | Purpose |
|---|---|
| `create(session, tenant_id, data)` | Insert a new `Document` row, status `processing` |
| `get_by_id(session, tenant_id, doc_id)` | Fetch one document (RLS-safe) |
| `get_by_idempotency_key(session, tenant_id, key)` | Used for idempotency check |
| `set_status(session, tenant_id, doc_id, status, error_reason)` | Update status only |

- Never return the SQLModel table object from functions that cross the service boundary;
  return the model internally and let the service convert to a DTO.
- All queries filter by `tenant_id` in addition to relying on RLS (defence in depth).

---

### T4 — Upload service

**New file:** `backend/app/services/upload_service.py`

`UploadService` class with two public async methods:

#### `request_upload(tenant_id, user_id, filename, content_type, size_bytes) -> PresignedUploadResponse`

1. Validate `content_type` against `settings.upload_allowed_content_types`; raise
   `ValidationError` if not in list.
2. Validate `size_bytes <= settings.upload_max_size_bytes`; raise `ValidationError` if exceeded.
3. Derive `idempotency_key = sha256(tenant_id + filename + str(size_bytes))` — deterministic
   so a retry of the same file doesn't create duplicate records.
4. Check `document_repo.get_by_idempotency_key`; if a `Document` already exists and is not
   `failed`, return the existing document id + a new presigned URL (re-upload is idempotent).
5. Generate `s3_key = f"{tenant_id}/{uuid4()}/{filename}"`.
6. Call S3 `generate_presigned_url` (PUT, expires in `settings.presigned_url_expires_seconds`,
   `ContentType` condition, `ContentLength` condition).
7. Create a `Document` record via `document_repo.create` with status `processing`.
8. Return `PresignedUploadResponse` (see T5).

#### `confirm_upload(tenant_id, document_id) -> DocumentResponse`

Called after the browser PUT completes. Enqueues the SQS ingestion job:

1. Fetch document; raise `NotFoundError` if missing or wrong tenant.
2. Publish message to `settings.sqs_queue_url`:
   ```json
   {
     "document_id": "<uuid>",
     "tenant_id": "<org_id>",
     "s3_key": "<key>",
     "idempotency_key": "<key>"
   }
   ```
3. Return `DocumentResponse`.

---

### T5 — Pydantic DTOs (schemas)

**New file:** `backend/app/schemas/document.py`

```python
class UploadRequestBody(BaseModel):
    filename: str          # original filename
    content_type: str
    size_bytes: int

class PresignedUploadResponse(BaseModel):
    document_id: UUID
    upload_url: str        # presigned PUT URL
    s3_key: str
    expires_in: int        # seconds

class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: str
    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str            # processing | ready | failed
    created_at: datetime
    # error_reason intentionally omitted — never leaked to API consumers
```

All fields explicitly typed; no `model_config = ConfigDict(from_attributes=True)` forgotten.

---

### T6 — Upload router

**New file:** `backend/app/routers/documents.py`

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/documents/upload-url` | required | Call `upload_service.request_upload`; return `PresignedUploadResponse` |
| `POST` | `/documents/{document_id}/confirm` | required | Call `upload_service.confirm_upload`; return `DocumentResponse` |
| `GET` | `/documents/{document_id}` | required | Return `DocumentResponse` for status polling |
| `GET` | `/documents` | required | List all documents for the tenant (id, title, status, created_at) |

- All routes inject `get_current_tenant` and `get_current_user`.
- The router is thin: validate input with Pydantic, call service, return DTO. Zero DB or AWS
  calls directly in the router.
- Register the router in `app/main.py` with prefix `/api/v1`.

---

### T7 — Ingestion worker

**New file:** `backend/worker/main.py` (new top-level `worker/` package)

Long-polling SQS worker loop:

```
while True:
    messages = sqs.receive_message(QueueUrl, MaxNumberOfMessages=10, WaitTimeSeconds=20)
    for msg in messages:
        await process_message(msg)
        sqs.delete_message(...)   # only on success
```

`process_message(msg)`:

1. Parse body JSON; extract `document_id`, `tenant_id`, `idempotency_key`.
2. Open a DB session; set RLS tenant context.
3. Fetch the document; skip if status is already `ready` (idempotent re-delivery).
4. **Stub for Phase 4:** log `"ingestion_stub: document_id={} tenant={}"` and sleep 1 s to
   simulate work.
5. On success: call `document_repo.set_status(session, tenant_id, doc_id, "ready")`.
6. On any exception: call `document_repo.set_status(..., "failed", error_reason=str(e))`;
   re-raise so the message is NOT deleted → SQS moves it to DLQ after `maxReceiveCount`.

Worker entrypoint: `python -m worker.main` (add to docker-compose as service `worker`).

---

### T8 — LocalStack / docker-compose wiring

**File:** `docker-compose.yml`

- Add a `localstack-init` step (or an `aws` CLI init container) that:
  - Creates the S3 bucket: `awslocal s3 mb s3://legal-documents`
  - Creates the SQS queue with a DLQ:
    ```
    awslocal sqs create-queue --queue-name legal-ingest-dlq
    awslocal sqs create-queue --queue-name legal-ingest \
      --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"...\",\"maxReceiveCount\":\"3\"}"}'
    ```
- Add a `worker` service pointing at `backend/worker/main.py`.
- Worker depends on `db` and `localstack`.

---

### T9 — Tests

**New file:** `backend/app/tests/test_upload.py`

Cover:

| Test | What it proves |
|---|---|
| `test_request_upload_returns_presigned_url` | Valid request → 200, url present, document created with status `processing` |
| `test_upload_rejects_invalid_content_type` | PDF-only policy enforced → 422 |
| `test_upload_rejects_oversized_file` | Size limit enforced → 422 |
| `test_confirm_enqueues_sqs_message` | After confirm, SQS queue has one message with correct `document_id` |
| `test_upload_is_idempotent` | Same idempotency key → same document_id, no duplicate rows |
| `test_get_document_returns_status` | Polling endpoint returns current status |
| `test_tenant_cannot_read_other_tenant_document` | Reuse RLS pattern: tenant B cannot GET tenant A's document → 404 |

**New file:** `backend/app/tests/test_worker.py`

| Test | What it proves |
|---|---|
| `test_worker_sets_status_ready` | Worker processes a valid message → status transitions to `ready` |
| `test_worker_sets_status_failed_on_error` | Injecting an error → status transitions to `failed` with reason |
| `test_worker_is_idempotent` | Delivering the same message twice → status stays `ready`, no exception |

Use `moto` (or LocalStack in docker) for S3/SQS mocking in unit tests; use the real DB for
repository-level tests (same pattern as Phase 2 RLS tests).

---

### T10 — Structured logging and error handling

Ensure Phase 3 additions follow existing patterns:

- All service and worker functions use the structured JSON logger from `app/core/logging.py`.
- Log `document_id`, `tenant_id`, `status` on every status transition.
- **Never** log `s3_key` with full path, `error_reason` verbatim, or document content.
- `ValidationError` (content type, size) → 422 via existing error handler.
- `NotFoundError` → 404.
- AWS client errors → 502 with a sanitized message; never leak boto3 internals to the client.

---

## File map (new + modified)

```
backend/
├── app/
│   ├── core/
│   │   └── config.py                   MODIFIED  (T1)
│   ├── infra/
│   │   └── aws.py                      NEW       (T2)
│   ├── repositories/
│   │   └── document_repo.py            NEW       (T3)
│   ├── services/
│   │   └── upload_service.py           NEW       (T4)
│   ├── schemas/
│   │   └── document.py                 NEW       (T5)
│   ├── routers/
│   │   └── documents.py                NEW       (T6)
│   ├── main.py                         MODIFIED  (register router)
│   └── tests/
│       ├── test_upload.py              NEW       (T9)
│       └── test_worker.py              NEW       (T9)
├── worker/
│   ├── __init__.py                     NEW       (T7)
│   └── main.py                         NEW       (T7)
├── .env.example                        MODIFIED  (T1)
└── pyproject.toml                      MODIFIED  (add aioboto3/moto)
docker-compose.yml                      MODIFIED  (T8)
```

---

## Done criteria checklist

- [ ] `POST /api/v1/documents/upload-url` returns a presigned S3 PUT URL and creates a
      `Document` row with status `processing`.
- [ ] `POST /api/v1/documents/{id}/confirm` enqueues an SQS message.
- [ ] Worker consumes the message and transitions status to `ready`.
- [ ] A failed message (after maxReceiveCount retries) ends up on the DLQ and the document
      status is `failed` with a reason.
- [ ] All T9 tests pass green.
- [ ] `ruff` and `black` pass with no violations.
