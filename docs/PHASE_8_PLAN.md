# Phase 8 — Cross-Reference Resolution

> **Goal:** When a clause contains a reference like "as defined in Section 2" or
> "subject to Exhibit B", allow the user to see the referenced text on demand —
> without leaving the current view.
>
> **Done when:** a clause with a cross-reference exposes the resolved target
> text on demand, with the resolved chunk linkable back to its location in the
> PDF viewer.

---

## Pre-conditions (already done)

- Chunker already detects cross-refs with `_XREF_RE` and stores them as a JSON
  array in `chunks.cross_refs` (e.g. `["Section 2.1", "Exhibit B"]`).
- Every chunk stores `section_number`, `heading`, `page`.
- PDF viewer can highlight any chunk via the existing `activeCitation` flow.

---

## Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| When is resolution triggered? | On-demand (`GET …/refs`) | Lazy; most chunks are never expanded |
| How are refs matched? | Normalised prefix match on `section_number`, then ILIKE on `heading` | Works for "Section 3.2" → chunk with section_number="3.2"; Exhibit/Schedule refs matched by heading |
| AI needed? | No | Structured refs (Section/Article/Exhibit) are matched deterministically using metadata already stored |
| Storage | No new table — resolution is computed at request time and cached in TanStack Query | Refs are cheap to resolve; no need to materialise |
| Unresolvable refs | Returned with `resolved: null` | Gives the UI something to display ("referenced section not found in document") |

---

## Normalisation rules

| Raw ref | Normalised key |
|---|---|
| `Section 3.2` | `3.2` |
| `section 3.2` | `3.2` |
| `Article IV` | `IV` |
| `Exhibit B` | `B` |
| `Schedule 1` | `1` |
| `clause 4.1` | `4.1` |

Resolution order per ref:
1. Exact match on `section_number` (normalised).
2. Prefix match on `section_number` (e.g. "3" matches "3.1", "3.2").
3. Case-insensitive `ILIKE '%<label>%'` on `heading`.
4. Return `null` if nothing matches.

---

## Task list

### T1 — Repository: `resolve_refs`

**Edit:** `backend/app/repositories/chunk_repo.py`

New function:

```python
async def resolve_refs(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    refs: list[str],          # raw strings from cross_refs JSON
) -> dict[str, Chunk | None]:
    """Return a mapping of raw_ref -> best matching Chunk (or None)."""
```

Uses a single query per unique normalised key:
- Try `section_number = <normalised>` (exact).
- Then `section_number LIKE '<normalised>.%'` (prefix).
- Then `heading ILIKE '%<label>%'` (e.g. "Exhibit B").

---

### T2 — Service: `cross_ref_service.py`

**New file:** `backend/app/services/cross_ref_service.py`

```python
async def get_resolved_refs(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
) -> list[ResolvedRef]:
    """
    Load the chunk's cross_refs JSON, resolve each ref to a target chunk,
    return a list of ResolvedRef objects.
    Raises NotFoundError if the chunk does not exist for this tenant+document.
    """
```

`ResolvedRef` dataclass (internal):
```python
@dataclass
class ResolvedRef:
    raw: str               # original text, e.g. "Section 3.2"
    normalised: str        # e.g. "3.2"
    target_chunk_id: uuid.UUID | None
    target_section: str | None
    target_heading: str | None
    target_page: int | None
    target_content: str | None  # first 400 chars of the resolved chunk
```

---

### T3 — Schema: `cross_ref.py`

**New file:** `backend/app/schemas/cross_ref.py`

```python
class ResolvedRefOut(BaseModel):
    raw: str
    normalised: str
    target_chunk_id: UUID | None
    target_section: str | None
    target_heading: str | None
    target_page: int | None
    target_content: str | None   # snippet of the resolved clause

class ChunkRefsResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    refs: list[ResolvedRefOut]
```

---

### T4 — Endpoint

**Edit:** `backend/app/api/v1/documents.py`

```
GET /api/v1/documents/{document_id}/chunks/{chunk_id}/refs
```

- Requires auth + tenant context.
- Returns 404 if chunk not found for tenant.
- Returns empty `refs: []` if chunk has no cross-refs.
- Returns resolved list (unresolvable refs included with `target_*: null`).

---

### T5 — Tests

**New file:** `backend/app/tests/test_cross_refs.py`

| Test | Proves |
|---|---|
| `test_resolve_exact_section` | "Section 2.1" resolves to chunk with section_number="2.1" |
| `test_resolve_exhibit` | "Exhibit B" resolves to chunk whose heading contains "Exhibit B" |
| `test_resolve_unresolvable` | "Section 99" returns entry with `target_chunk_id: null` |
| `test_resolve_empty_refs` | Chunk with no cross-refs returns `refs: []` |
| `test_resolve_requires_auth` | 401 for unauthenticated |
| `test_resolve_tenant_isolation` | Cannot resolve refs from another tenant's document |

---

### T6 — Frontend BFF + CrossRefPanel

**New BFF route:** `frontend/src/app/api/documents/[docId]/chunks/[chunkId]/refs/route.ts`
- `GET` → proxies to backend with Clerk token.

**New component:** `frontend/src/components/cross-ref-panel.tsx`
- Fetches resolved refs for the active citation's `chunk_id`.
- Renders each ref as an expandable row: raw label → resolved section + content snippet.
- "Go to clause" button calls `onCitationClick` with the resolved `target_chunk_id` → highlights the target in the PDF.
- Unresolved refs shown with muted "not found in document" label.
- Mounted inside `DocLayout` below the active citation, visible only when a citation is selected and it has refs.

---

## File map

```
backend/app/repositories/chunk_repo.py              MOD  (T1 — add resolve_refs)
backend/app/services/cross_ref_service.py           NEW  (T2)
backend/app/schemas/cross_ref.py                    NEW  (T3)
backend/app/api/v1/documents.py                     MOD  (T4 — add /chunks/{id}/refs)
backend/app/tests/test_cross_refs.py                NEW  (T5)
frontend/src/app/api/documents/[docId]/chunks/[chunkId]/refs/route.ts  NEW  (T6)
frontend/src/lib/types.ts                           MOD  (T6 — add ResolvedRef types)
frontend/src/lib/api.ts                             MOD  (T6 — add getChunkRefs helper)
frontend/src/components/cross-ref-panel.tsx         NEW  (T6)
frontend/src/components/doc-layout.tsx              MOD  (T6 — mount CrossRefPanel)
```

---

## Done criteria checklist

- [ ] `GET /api/v1/documents/{id}/chunks/{chunk_id}/refs` returns resolved refs for a clause.
- [ ] "Section X.Y" resolves to the correct chunk by `section_number`.
- [ ] "Exhibit B" / "Schedule 1" resolves by `heading` ILIKE.
- [ ] Unresolvable refs returned with `target_chunk_id: null` (not an error).
- [ ] Tenant A cannot resolve refs from Tenant B's document.
- [ ] Frontend shows resolved ref snippets below the active citation.
- [ ] Clicking "Go to clause" on a resolved ref highlights the target in the PDF.
- [ ] `ruff` passes.
