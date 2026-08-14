# Phase 5 — Grounded Q&A (MVP core)

> **Goal:** Given a natural-language question, retrieve tenant-scoped clause chunks via
> hybrid dense + sparse search, fuse with RRF, rerank, and generate a grounded answer
> via Bedrock Claude that cites supporting clauses — or returns
> `"not found in your documents."` when nothing supports the claim.
>
> **Done when:** an answerable question returns a grounded, cited answer; an
> unanswerable one returns the not-found phrase; every citation references a real
> chunk (`document_id`, `chunk_id`, `section`, `quote`).

---

## Pre-conditions (already done)

- Phase 4 complete: chunks stored with `embedding` (1024-dim) + `search_vector` (tsvector),
  HNSW and GIN indexes present.
- Conversation / Message tables + RLS exist (no API yet).
- Shared `embed_texts` used for document embeddings (must add query `input_type`).
- Auth, tenant deps, `get_rls_db` established.

---

## Task list

### T1 — Extend Settings

**File:** `backend/app/core/config.py` + root `.env.example`

```
# Retrieval
retrieval_dense_top_k: int = 40
retrieval_sparse_top_k: int = 40
retrieval_rrf_k: int = 60
retrieval_rerank_top_n: int = 8

# Cohere Rerank (empty → local lexical fallback for dev/CI)
cohere_api_key: str = ""
cohere_rerank_model: str = "rerank-english-v3.0"

# Bedrock Claude (empty model / no credentials → deterministic local stub for CI)
bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
generation_max_tokens: int = 1024
generation_temperature: float = 0.0
```

---

### T2 — Embedder: query input type

**File:** `backend/app/ingestion/embedder.py`

- Add `input_type: Literal["document", "query"] = "document"` to `embed_texts`.
- Add `async def embed_query(text: str) -> list[float]` convenience wrapper.
- Voyage payload must pass the chosen `input_type`. Local fallback ignores it
  (still deterministic).

---

### T3 — Chunk repository search

**File:** `backend/app/repositories/chunk_repo.py`

```python
@dataclass(frozen=True, slots=True)
class RankedChunk:
    chunk: Chunk
    score: float  # provider-native score (distance or ts_rank)

async def dense_search(
    session, tenant_id, query_embedding, *, top_k, document_id=None,
    embedding_model, embedding_model_version,
) -> list[RankedChunk]:
    """Cosine nearest neighbours via pgvector <=> . Filter by tenant + model."""

async def sparse_search(
    session, tenant_id, query_text, *, top_k, document_id=None,
) -> list[RankedChunk]:
    """BM25-style via plainto_tsquery + ts_rank_cd on search_vector."""

async def get_by_ids(session, tenant_id, chunk_ids) -> list[Chunk]:
    """Fetch chunks by id for citation validation."""
```

All queries filter by `tenant_id`. Optional `document_id` scopes to one document.
Dense search also filters `embedding_model` / `embedding_model_version` so vectors
are never mixed.

---

### T4 — RRF fusion (pure)

**New file:** `backend/app/retrieval/rrf.py`

```python
def reciprocal_rank_fusion(
    ranked_lists: list[list[uuid.UUID]],
    *,
    k: int = 60,
) -> list[tuple[uuid.UUID, float]]:
    """Return (chunk_id, rrf_score) sorted descending."""
```

Zero I/O. Unit-tested thoroughly.

---

### T5 — Rerank

**New file:** `backend/app/retrieval/rerank.py`

```python
async def rerank(
    query: str,
    candidates: list[Chunk],
    *,
    top_n: int,
) -> list[Chunk]:
```

- Cohere Rerank API when `settings.cohere_api_key` is set.
- Else local lexical fallback: score by overlapping query tokens in content
  (stable, deterministic for tests).

---

### T6 — Retrieval service

**New file:** `backend/app/services/retrieval_service.py`

```python
async def retrieve(
    session, tenant_id, question, *, document_id=None,
) -> list[Chunk]:
    """embed_query → dense + sparse → RRF → rerank → top_n chunks."""
```

Logs counts only; never logs question text or chunk content in full.

---

### T7 — Generation (Bedrock grounding)

**New file:** `backend/app/infra/bedrock.py`  
**New file:** `backend/app/services/generation_service.py`

```python
@dataclass(frozen=True, slots=True)
class Citation:
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    section: str | None
    quote: str

@dataclass(frozen=True, slots=True)
class GenerationResult:
    answer: str
    citations: list[Citation]
    not_found: bool
```

Rules:
- System prompt: document comprehension only, never legal advice; every claim
  must cite a provided clause; if unsupported → exact phrase
  `"not found in your documents."`
- Pass only the reranked chunks as context (id, section, content).
- Parse structured JSON from the model: `{ "answer": "...", "citations": [...] }`.
- Drop any citation whose `chunk_id` is not in the provided set (never fabricate).
- When `citations` empty or model says not found → force the not-found phrase.
- Local stub (no Bedrock / LocalStack Converse unavailable): if candidates empty →
  not-found; else return a short grounded paraphrase citing the top chunk.

Use `aioboto3` `bedrock-runtime` `converse` (or `invoke_model`). Reuse AWS
client kwargs from `app/infra/aws.py` (add `get_bedrock_runtime_client`).

---

### T8 — Conversation / message repos + QA service

**New files:**
- `backend/app/repositories/conversation_repo.py`
- `backend/app/repositories/message_repo.py`
- `backend/app/services/qa_service.py`

```python
async def ask(
    session, tenant_id, user_id, question,
    *, document_id=None, conversation_id=None,
) -> QueryResponse:
    """
    1. Resolve / create Conversation (tenant-scoped).
    2. Persist user Message.
    3. retrieve → generate.
    4. Persist assistant Message (citations JSON).
    5. Return DTO.
    """
```

If `document_id` is provided, verify it exists for the tenant (404 otherwise).
Optional: reject documents that are not `ready` with 422.

---

### T9 — Schemas + query router

**New files:**
- `backend/app/schemas/query.py`
- `backend/app/api/v1/query.py`

```
POST /api/v1/query
Body: { question: str, document_id?: UUID, conversation_id?: UUID }
Response: {
  conversation_id, message_id, answer, not_found,
  citations: [{ document_id, chunk_id, section, quote }]
}
```

Wire in `main.py`. Router is thin — auth + DTO only.

---

### T10 — Tests

**`backend/app/tests/test_rrf.py`** (pure)

| Test | Proves |
|---|---|
| `test_rrf_promotes_overlap` | IDs in both lists rank above single-list IDs |
| `test_rrf_stable_order` | Deterministic for same inputs |
| `test_rrf_empty` | Empty lists → empty result |

**`backend/app/tests/test_query.py`** (HTTP + DB, mocks for embed/rerank/bedrock)

| Test | Proves |
|---|---|
| `test_query_returns_grounded_citation` | Answerable Q → citations with real chunk ids |
| `test_query_not_found` | No supporting chunks → not-found phrase |
| `test_query_requires_auth` | Unauthenticated → 401 |
| `test_query_tenant_isolation` | Tenant A cannot cite Tenant B chunks |

---

## File map

```
docs/PHASE_5_PLAN.md                         NEW
backend/app/core/config.py                   MODIFIED  (T1)
.env.example                                 MODIFIED  (T1)
backend/app/ingestion/embedder.py            MODIFIED  (T2)
backend/app/repositories/chunk_repo.py       MODIFIED  (T3)
backend/app/retrieval/__init__.py            NEW
backend/app/retrieval/rrf.py                 NEW       (T4)
backend/app/retrieval/rerank.py              NEW       (T5)
backend/app/services/retrieval_service.py    NEW       (T6)
backend/app/infra/bedrock.py                 NEW       (T7)
backend/app/infra/aws.py                     MODIFIED  (bedrock client)
backend/app/services/generation_service.py   NEW       (T7)
backend/app/repositories/conversation_repo.py NEW      (T8)
backend/app/repositories/message_repo.py     NEW       (T8)
backend/app/services/qa_service.py           NEW       (T8)
backend/app/schemas/query.py                 NEW       (T9)
backend/app/api/v1/query.py                  NEW       (T9)
backend/app/main.py                          MODIFIED  (T9)
backend/app/tests/test_rrf.py                NEW       (T10)
backend/app/tests/test_query.py              NEW       (T10)
```

---

## Done criteria checklist

- [x] `POST /api/v1/query` returns a grounded answer with structured citations.
- [x] Unanswerable questions return exactly `not found in your documents.`
- [x] Citations only reference retrieved tenant-owned chunks.
- [x] Dense + sparse + RRF + rerank path is covered by unit/integration tests.
- [x] Auth required; cross-tenant citation impossible.
- [x] `ruff` and `black` pass.

> Note: DB-backed query integration tests need Postgres running
> (`docker compose up -d db`). Unit tests for RRF, generation, and auth pass
> without it.
