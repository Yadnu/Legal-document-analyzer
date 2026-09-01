# Phase 9 — Multi-Document Workspace

> **Goal:** Users can ask questions that span all of their uploaded documents and
> receive grounded, per-document cited answers.  The workspace landing page
> becomes a full Q&A surface; citations identify which document they come from
> and navigating to one opens the right PDF with the clause highlighted.
>
> **Done when:** a cross-document question cites the right document and clause
> for each point.

---

## Pre-conditions (already done)

- `retrieve()` already accepts `document_id=None` → searches all tenant chunks.
- `qa_service.ask()` already accepts `document_id=None` → creates a
  workspace-level conversation (`Conversation.document_id IS NULL`).
- `CitationOut` already carries `document_id` per citation.
- Frontend chat panel and citation chips already exist.

---

## Architecture decisions

| Decision | Choice | Reason |
|---|---|---|
| Do we need new retrieval code? | No | `retrieve(document_id=None)` already spans all docs |
| How does the frontend know the document title for each citation? | Add `document_title` to `CitationOut` server-side | Avoids a waterfall of extra fetches; single enriched response |
| Where does workspace chat live? | Workspace page (`/workspace`) — right panel alongside the document list | Consistent with doc-level layout; user sees all docs and can chat |
| Cross-doc citation click action | Navigate to `/workspace/[docId]?chunk=[id]&quote=[text]` | Opens the correct PDF viewer with the cited clause highlighted |
| Conversation persistence | Reuse existing Conversation model; `document_id=NULL` = workspace conv | No schema change needed |
| List workspace conversations | New `GET /api/v1/conversations` endpoint scoped to tenant | Lets the UI resume past cross-doc conversations |

---

## Task list

### T1 — Enrich CitationOut with document title

**Edit:** `backend/app/schemas/query.py`

Add `document_title: str | None = None` to `CitationOut`.

**Edit:** `backend/app/services/qa_service.py`

After generation, batch-fetch titles for all cited `document_id`s and attach:

```python
cited_ids = {c.document_id for c in result.citations}
docs = await document_repo.get_many_by_ids(session, tenant_id, list(cited_ids))
title_map = {d.id: d.title for d in docs}
```

**Edit:** `backend/app/repositories/document_repo.py`

Add `get_many_by_ids(session, tenant_id, ids)` — single `WHERE id IN (...)` query.

---

### T2 — Conversations list endpoint

**New endpoint** in `backend/app/api/v1/query.py`:

```
GET /api/v1/conversations
```

Returns the tenant's most recent 20 workspace conversations
(`document_id IS NULL`), newest first.

**New schema** in `backend/app/schemas/query.py`:

```python
class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    message_count: int
```

**New repo function** in `backend/app/repositories/conversation_repo.py`:

```python
async def list_workspace_conversations(
    session, tenant_id, *, limit=20
) -> list[ConversationSummary]
```

---

### T3 — Tests

**New file:** `backend/app/tests/test_multidoc.py`

| Test | Proves |
|---|---|
| `test_cross_doc_returns_citations_from_both_docs` | Question answered with citations spanning 2 docs |
| `test_cross_doc_citations_include_document_title` | Each `CitationOut.document_title` is non-null |
| `test_workspace_conversation_has_null_document_id` | Conversation created without `document_id` |
| `test_list_conversations_returns_workspace_convs` | `GET /conversations` returns workspace conversations |
| `test_list_conversations_requires_auth` | 401 for unauthenticated |

---

### T4 — Frontend: workspace chat

**Edit:** `frontend/src/app/workspace/page.tsx`

Split the workspace page into a two-column layout:
- Left: existing `DocumentList`
- Right: new `WorkspaceChat` component (workspace-level Q&A)

**New component:** `frontend/src/components/workspace-chat.tsx`

Reuses `ChatPanel` logic but:
- Sends `POST /api/query` with no `document_id`
- Citation chips show `§section · DocumentTitle` instead of just `§section`
- Clicking a citation navigates to `/workspace/[docId]?chunk=[id]&quote=[text]`

**New BFF route:** `frontend/src/app/api/conversations/route.ts`
- `GET` → proxies `GET /api/v1/conversations`

---

### T5 — Frontend: cross-doc citation navigation

**Edit:** `frontend/src/app/workspace/[docId]/page.tsx`

Read `chunk` and `quote` search params; if present, pass them as
`initialCitation` to `DocLayout` which feeds them into `activeCitation`
so the PDF highlights the cited clause on first load.

**Edit:** `frontend/src/components/doc-layout.tsx`

Accept optional `initialCitation?: CitationOut` prop; set it as the initial
`activeCitation` state.

---

## File map

```
backend/app/repositories/document_repo.py          MOD  (T1 — add get_many_by_ids)
backend/app/repositories/conversation_repo.py      MOD  (T2 — add list_workspace_conversations)
backend/app/schemas/query.py                       MOD  (T1 — document_title on CitationOut;
                                                         T2 — ConversationSummary)
backend/app/services/qa_service.py                 MOD  (T1 — enrich citations with title)
backend/app/api/v1/query.py                        MOD  (T2 — add GET /conversations)
backend/app/tests/test_multidoc.py                 NEW  (T3)
frontend/src/app/workspace/page.tsx                MOD  (T4 — two-column layout + WorkspaceChat)
frontend/src/components/workspace-chat.tsx         NEW  (T4)
frontend/src/app/api/conversations/route.ts        NEW  (T4 — BFF)
frontend/src/lib/types.ts                          MOD  (T1 — document_title on CitationOut)
frontend/src/app/workspace/[docId]/page.tsx        MOD  (T5 — read chunk/quote params)
frontend/src/components/doc-layout.tsx             MOD  (T5 — initialCitation prop)
```

---

## Done criteria checklist

- [ ] `POST /query` with no `document_id` returns citations from multiple documents.
- [ ] Every `CitationOut` carries `document_title`.
- [ ] `GET /conversations` returns workspace-level conversations for the tenant.
- [ ] Workspace page shows document list + cross-document chat side-by-side.
- [ ] Workspace citation chips display the document name.
- [ ] Clicking a workspace citation opens the correct document with the clause highlighted.
- [ ] `ruff` passes.
