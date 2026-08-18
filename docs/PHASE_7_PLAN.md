# Phase 7 — Structured Clause Extraction

> **Goal:** When a user opens a document, display a summary card with seven
> structured fields (parties, effective date, term length, payment terms,
> termination rights, liability caps, governing law). Every field is grounded
> — it cites the exact clause it was drawn from — and clicking a citation
> highlights the clause in the PDF viewer exactly as chat citations do.
>
> **Done when:** opening a document shows an accurate card, each field linking
> to its source clause.

---

## Pre-conditions (already done)

- Phase 6 complete: PDF viewer with citation highlight, chat Q&A, explain-clause.
- `retrieve()` + `generate_answer()` + Bedrock `converse_text()` all working.
- `Citation` dataclass, chunk repo search, RRF, rerank all in place.
- `TenantModel` base class with RLS.

---

## Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| When is extraction triggered? | On-demand (first `GET /summary` call) | Extraction takes ~10 s; triggering lazily avoids extending the "ready" transition and lets the UI show a skeleton |
| How many Bedrock calls per document? | One combined call | Pass top chunks once; ask for all 7 fields in a single structured JSON response — more efficient and gives cross-field context |
| Storage | Separate `document_summary_cards` table, one row per document | Clean separation; easy upsert / invalidation; RLS inherited from `TenantModel` |
| Field granularity | Each field stored as a `JSONB` column: `{value, chunk_id, section, quote}` | Lets the API return typed citations per field without an auxiliary join |
| Re-extraction | Upsert on every call if older than 24 h (or never exists) | Handles documents that were re-ingested with new chunks |

---

## Task list

### T1 — DB model + Alembic migration

**New file:** `backend/app/models/summary.py`

```python
class SummaryField(TypedDict):
    value: str | None
    chunk_id: str | None     # UUID as string
    section: str | None
    quote: str | None

class DocumentSummaryCard(TenantModel, table=True):
    __tablename__ = "document_summary_cards"

    document_id: uuid.UUID = Field(nullable=False, index=True,
                                   foreign_key="documents.id")
    parties:             str | None = Field(default=None, sa_column=Column(JSONB))
    effective_date:      str | None = Field(default=None, sa_column=Column(JSONB))
    term_length:         str | None = Field(default=None, sa_column=Column(JSONB))
    payment_terms:       str | None = Field(default=None, sa_column=Column(JSONB))
    termination_rights:  str | None = Field(default=None, sa_column=Column(JSONB))
    liability_caps:      str | None = Field(default=None, sa_column=Column(JSONB))
    governing_law:       str | None = Field(default=None, sa_column=Column(JSONB))
    extracted_at: datetime = Field(...)
```

**Alembic migration** — auto-generate from model, add RLS policy:
```sql
ALTER TABLE document_summary_cards ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON document_summary_cards
    USING (tenant_id = current_setting('app.tenant_id'));
```

---

### T2 — Summary repository

**New file:** `backend/app/repositories/summary_repo.py`

```python
async def get_for_document(session, tenant_id, document_id) -> DocumentSummaryCard | None
async def upsert(session, tenant_id, document_id, fields: dict) -> DocumentSummaryCard
```

All queries filter by `tenant_id` (RLS is defence-in-depth).

---

### T3 — Extraction service

**New file:** `backend/app/services/extraction_service.py`

**Strategy:**
1. Run `retrieve()` with a broad question ("parties effective date term payment termination liability governing law") to pull the most relevant chunks across all fields — one retrieval call.
2. Pass the top chunks to a single Bedrock call with a structured prompt that requests all 7 fields as JSON.
3. Drop any `chunk_id` not in the provided set (same fabrication guard as Q&A).
4. Upsert to DB; return the card DTO.

**Prompt shape:**
```
System: Legal document comprehension only. Extract the following fields
        from the provided clauses. Return JSON only with this exact shape:
        {
          "parties":            {"value": "...", "chunk_id": "...", "quote": "..."},
          "effective_date":     ...,
          "term_length":        ...,
          "payment_terms":      ...,
          "termination_rights": ...,
          "liability_caps":     ...,
          "governing_law":      ...
        }
        Set a field to null if the clauses do not support it.
        chunk_id must be one of the provided chunk IDs.

User: [chunks], extract fields.
```

**Local stub** (Bedrock unavailable): if top chunk exists, return `value = "see document"` citing that chunk for each field; no fabrication.

**Cache TTL:** re-extract if `extracted_at` is older than 24 hours.

---

### T4 — Schema + endpoint

**New file:** `backend/app/schemas/summary.py`

```python
class SummaryFieldOut(BaseModel):
    value: str | None
    chunk_id: UUID | None
    section: str | None
    quote: str | None

class DocumentSummaryCardResponse(BaseModel):
    document_id: UUID
    parties:             SummaryFieldOut
    effective_date:      SummaryFieldOut
    term_length:         SummaryFieldOut
    payment_terms:       SummaryFieldOut
    termination_rights:  SummaryFieldOut
    liability_caps:      SummaryFieldOut
    governing_law:       SummaryFieldOut
    extracted_at: datetime
```

**New endpoint** (added to `backend/app/api/v1/documents.py`):

```
GET /api/v1/documents/{document_id}/summary
```

- If summary exists and is fresh (< 24 h): return immediately.
- If not: run `extraction_service.extract(session, tenant_id, document_id)`, store, return.
- 404 if document doesn't exist for tenant.
- 422 if document status is not `ready`.

---

### T5 — Tests

**`backend/app/tests/test_extraction.py`**

| Test | Proves |
|---|---|
| `test_extraction_returns_all_fields` | All 7 fields present in response |
| `test_extraction_citations_are_valid` | Every `chunk_id` in the card belongs to the document's chunks |
| `test_extraction_cached` | Second call returns same `extracted_at` (no re-extract within TTL) |
| `test_extraction_requires_ready_document` | Returns 422 for `processing` document |
| `test_extraction_tenant_isolation` | Tenant A cannot read Tenant B summary |

---

### T6 — Frontend BFF + SummaryCard component

**New BFF route:** `frontend/src/app/api/documents/[docId]/summary/route.ts`
- `GET` → proxies to `GET /api/v1/documents/{id}/summary` with Clerk token.

**New component:** `frontend/src/components/summary-card.tsx`

- Uses `useQuery` with `queryKey: ["summary", documentId]`.
- Shows a 7-row card; each row: field label + value + a citation chip.
- Clicking the citation chip calls `onCitationClick` (same callback already wired in DocLayout) → highlights the clause in the PDF viewer.
- **Loading state:** skeleton rows while the first extraction runs (~10 s); the query retries automatically.
- **Null fields:** show "—" with muted styling.
- **Stale-time:** match the 24-hour extraction TTL so the client doesn't re-fetch unnecessarily.

**Integration:** add `SummaryCard` as a collapsible section at the top of `ChatPanel` (or as a tab above it) so it doesn't steal screen space from the conversation.

---

## File map

```
backend/app/models/summary.py                NEW  (T1)
backend/alembic/versions/0002_summary.py     NEW  (T1)
backend/app/repositories/summary_repo.py     NEW  (T2)
backend/app/services/extraction_service.py   NEW  (T3)
backend/app/schemas/summary.py               NEW  (T4)
backend/app/api/v1/documents.py              MOD  (T4 — add /summary endpoint)
backend/app/tests/test_extraction.py         NEW  (T5)
frontend/src/app/api/documents/[docId]/summary/route.ts  NEW  (T6)
frontend/src/lib/api.ts                      MOD  (T6 — add getSummary helper)
frontend/src/lib/types.ts                    MOD  (T6 — add summary types)
frontend/src/components/summary-card.tsx     NEW  (T6)
frontend/src/components/doc-layout.tsx       MOD  (T6 — wire summary card in)
```

---

## Done criteria checklist

- [ ] `GET /api/v1/documents/{id}/summary` returns all 7 fields with citations.
- [ ] Each citation `chunk_id` references a real chunk owned by the tenant.
- [ ] Second call within 24 h returns cached result (no re-extraction).
- [ ] `processing` document returns 422; missing document returns 404.
- [ ] Tenant A cannot see Tenant B summary.
- [ ] Frontend summary card renders with skeleton during extraction, then shows all fields.
- [ ] Clicking a field's citation chip highlights the clause in the PDF viewer.
- [ ] `ruff` and `black` pass.
