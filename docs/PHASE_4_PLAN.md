# Phase 4 — Ingestion Pipeline

> **Goal:** The worker replaces its Phase 3 stub with a real pipeline that downloads the
> uploaded file from S3, parses it into structured elements, chunks those elements into
> clause-level units with section metadata, embeds each chunk with a single versioned
> embedding function, and stores the resulting `Chunk` rows (dense vector + tsvector)
> idempotently in Postgres.
>
> **Done when:** after uploading a PDF, status reaches `ready`, the `chunks` table
> contains clause-level rows with correct `section_number`, `heading`, `page`, and
> `cross_refs` metadata, the `embedding` column is populated, and re-running the same
> document produces zero duplicate rows.

---

## Pre-conditions (already done)

- Phase 3 complete: worker consumes SQS messages; `process_message` contains a stub.
- `Chunk` SQLModel with all columns (`embedding` Vector(1024), `search_vector` TSVECTOR,
  `section_number`, `heading`, `page`, `cross_refs`, `token_count`,
  `embedding_model`, `embedding_model_version`) defined and migrated.
- `Document.page_count` column exists (optional int).
- `get_s3_client()` factory in `app/infra/aws.py`.
- `settings` loaded from env via pydantic-settings.

---

## Task list

### T1 — Extend Settings

**File:** `backend/app/core/config.py`

Add:
```
# Voyage AI
voyage_api_key: str = ""

# Embedding model — same name used for BOTH document chunks and query embeddings.
# Changing this requires re-embedding all existing chunks.
embedding_model: str = "voyage-law-2"
embedding_model_version: str = "1"
embedding_dimensions: int = 1024

# Optional: LlamaParse API key (leave empty to use the local PyMuPDF parser)
llama_parse_api_key: str = ""

# Chunking policy
chunk_max_tokens: int = 512
chunk_overlap_tokens: int = 64
```

Update `backend/.env.example` with matching entries.

---

### T2 — S3 download helper

**New file:** `backend/app/infra/storage.py`

```python
async def download_document(s3_key: str) -> bytes:
    """Download raw bytes for a document from S3."""
```

- Uses `get_s3_client()`.
- Raises `AwsError` on `ClientError`.
- Never logs the s3_key in full; log only the last 16 chars.

---

### T3 — Parser module

**New file:** `backend/app/ingestion/parser.py`

```python
@dataclass(frozen=True, slots=True)
class ParsedElement:
    text: str           # raw text of the element
    element_type: str   # "heading" | "narrative" | "list_item" | "table"
    page: int           # 1-indexed page number
    section_number: str | None   # e.g. "3.2", "Article IV"
    heading: str | None          # nearest heading text above this element
```

```python
def parse_pdf(data: bytes) -> list[ParsedElement]:
    """Parse a PDF into structured elements using PyMuPDF.

    Detects headings by font-size heuristic (> 1.2× median body font size).
    Preserves page numbers.  Returns elements in document order.
    """
```

- Pure function; no I/O.
- Falls back to a flat list of `narrative` elements if structure detection fails.
- **Install:** add `pymupdf>=1.24` to `pyproject.toml`.

---

### T4 — Chunker module

**New file:** `backend/app/ingestion/chunker.py`

```python
@dataclass(frozen=True, slots=True)
class ChunkData:
    content: str
    section_number: str | None
    heading: str | None
    page: int | None
    cross_refs: list[str]   # resolved section references in this chunk
    token_count: int
```

```python
def chunk_elements(
    elements: list[ParsedElement],
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> list[ChunkData]:
```

Rules:
- Group consecutive `narrative` / `list_item` elements under the same heading/section.
- Split if accumulated token count would exceed `max_tokens`.
- Each chunk carries the `section_number` and `heading` of its section.
- Cross-reference extraction: scan `content` for patterns like
  `Section 3.2`, `Article IV`, `Exhibit B`, `Schedule 1`, `Appendix A`.
- Token count: `len(content.split())` is acceptable for Phase 4
  (replace with tiktoken in Phase 5 when token budgets matter).
- Headings become standalone chunks of type `heading` if they carry no body text.

This module must have **zero external dependencies** (no DB, no AWS, no AI).
Unit tests cover it completely.

---

### T5 — Embedder module

**New file:** `backend/app/ingestion/embedder.py`

```python
async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per text.

    Provider selection (in priority order):
    1. Voyage AI — when settings.voyage_api_key is set.
    2. Local fallback — deterministic unit-sphere vectors derived from a
       SHA-256 hash of each text, padded to settings.embedding_dimensions.
       Use ONLY for local development / CI; never in production.
    """
```

- Voyage AI: `POST https://api.voyageai.com/v1/embeddings` with model
  `settings.embedding_model`.
- Batch texts in groups of 128 (Voyage limit).
- Raises `AwsError` (reuse existing exception) on HTTP failure.
- The local fallback must be deterministic so tests are reproducible.
- **Install:** add `httpx` (already present) — no new dep needed for Voyage.

---

### T6 — Chunk repository

**New file:** `backend/app/repositories/chunk_repo.py`

```python
async def upsert_chunks(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
    embedding_model: str,
    embedding_model_version: str,
) -> int:
    """Delete all existing chunks for the document, then insert the new set.

    Returns the count of inserted rows.
    Idempotent: calling twice with the same data produces the same DB state.
    Sets search_vector via to_tsvector('english', content) in the INSERT.
    """
```

- Delete-then-insert is simpler and safer than true upsert for the initial pipeline.
- The `search_vector` column is populated inside the INSERT using a SQL expression:
  `to_tsvector('english', :content)` so no separate trigger is needed.
- All queries filter by both `tenant_id` and `document_id`.

---

### T7 — Ingestion service

**New file:** `backend/app/services/ingestion_service.py`

```python
async def ingest(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    s3_key: str,
) -> int:
    """Full ingestion pipeline.  Returns chunk count.

    1. Download raw bytes from S3.
    2. Determine content_type from the Document row.
    3. Parse → list[ParsedElement].
    4. Chunk → list[ChunkData].
    5. Embed → list[list[float]].
    6. Upsert chunks (idempotent).
    7. Update Document.page_count.
    8. Return chunk count.
    """
```

- Uses `settings.chunk_max_tokens` and `settings.chunk_overlap_tokens`.
- Logs `document_id`, `tenant_id`, `chunk_count`, `page_count` on success.
- Never logs file bytes or chunk content.

---

### T8 — Wire worker

**File:** `backend/worker/main.py`

Replace the stub block:
```python
# ── Phase 4 stub ─────────────────────────────────────────────────
bound_log.info("ingestion_stub", ...)
await asyncio.sleep(1)
# ── End stub ─────────────────────────────────────────────────────
```

with:
```python
from app.services.ingestion_service import ingest

chunk_count = await ingest(
    session=session,
    tenant_id=tenant_id,
    document_id=doc_id,
    s3_key=body["s3_key"],
)
bound_log.info("worker_ingested", chunk_count=chunk_count)
```

---

### T9 — Alembic migration

**New file:** `backend/alembic/versions/0002_chunks_tsvector_index.py`

The `chunks` table already exists from Phase 2. This migration adds any missing
index if Alembic's autogenerate detects drift, and ensures the HNSW and GIN
indexes are present. Run `alembic revision --autogenerate -m "chunks indexes"`
and review the output; adjust if needed.

---

### T10 — Tests

**New file:** `backend/app/tests/test_chunker.py`

Pure unit tests — no DB, no network:

| Test | What it proves |
|---|---|
| `test_chunk_simple_narrative` | Flat text → at least one chunk |
| `test_chunk_respects_max_tokens` | No chunk exceeds `max_tokens` words |
| `test_chunk_preserves_section_metadata` | Section number + heading carried through |
| `test_chunk_extracts_cross_refs` | "See Section 3.2" detected in `cross_refs` |
| `test_chunk_idempotent` | Calling twice with same input yields same output |

**New file:** `backend/app/tests/test_ingestion.py`

Integration tests with mocked S3 + Voyage (real DB):

| Test | What it proves |
|---|---|
| `test_ingest_creates_chunks` | After ingest, chunks exist with correct tenant + document_id |
| `test_ingest_sets_page_count` | `Document.page_count` updated after ingest |
| `test_ingest_is_idempotent` | Running ingest twice → same chunk count, no duplicates |
| `test_ingest_tenant_isolation` | Chunks are only visible to the owning tenant |

---

## File map (new + modified)

```
backend/
├── app/
│   ├── core/
│   │   └── config.py               MODIFIED  (T1)
│   ├── infra/
│   │   └── storage.py              NEW       (T2)
│   ├── ingestion/
│   │   ├── __init__.py             NEW
│   │   ├── parser.py               NEW       (T3)
│   │   ├── chunker.py              NEW       (T4)
│   │   └── embedder.py             NEW       (T5)
│   ├── repositories/
│   │   └── chunk_repo.py           NEW       (T6)
│   ├── services/
│   │   └── ingestion_service.py    NEW       (T7)
│   └── tests/
│       ├── test_chunker.py         NEW       (T10)
│       └── test_ingestion.py       NEW       (T10)
├── worker/
│   └── main.py                     MODIFIED  (T8)
├── alembic/versions/
│   └── 0002_chunks_indexes.py      NEW       (T9)
├── pyproject.toml                  MODIFIED  (pymupdf)
└── .env.example                    MODIFIED  (T1)
```

---

## Done criteria checklist

- [ ] Uploading a PDF triggers the worker and creates clause-level `Chunk` rows.
- [ ] Each chunk has `section_number`, `heading`, `page`, `cross_refs` populated where
      available.
- [ ] `embedding` (1024-dim vector) and `search_vector` (tsvector) are set on every row.
- [ ] `Document.page_count` is updated after ingestion.
- [ ] Re-ingesting the same document produces the same chunk count (idempotent).
- [ ] All T10 tests pass green.
- [ ] `ruff` and `black` pass with no violations.
