# Current State

This document supersedes any older design notes that still mention localStorage
chat persistence or Prompt Template / Prompt Pack runtime support.

## Chat Persistence

- Conversations and messages are now persisted in backend SQLite.
- The source of truth is `backend/services/storage.py`.
- Frontend chat state is a runtime cache backed by:
  - `GET /api/chat/state`
  - `POST /api/conversations`
  - `PUT /api/conversations/{id}`
  - `DELETE /api/conversations/{id}`
  - `POST /api/conversations/{id}/messages`
  - `PUT /api/messages/{id}`
- `src/stores/chatStore.ts` no longer uses localStorage as chat history storage.
- `src/stores/appStore.ts` still persists UI and LLM configuration locally.

## RAG by Role Capability

- RAG is no longer hardcoded to `copilot`.
- Any role whose `capabilities` contains `rag` can trigger context retrieval.
- Capability gating happens in `backend/routers/chat.py`.
- Context assembly is role-agnostic in `backend/services/context_assembler.py`.
- If the current role lacks `rag`, chat falls back to plain generation without retrieval.

## Prompt Template / Prompt Pack

- Prompt Template / Prompt Pack has been removed from the backend product surface.
- The real chat path only uses:
  - role `system_prompt`
  - saved `system_prompt_{role_id}` overrides
  - system prompt presets
- Removed backend runtime surface:
  - Prompt Template service
  - Prompt Template / Prompt Pack settings routes
- Existing historical data, if any, is ignored by the live product.

## Current Backend Settings Surface

- Roles: `backend/routers/settings.py`
- Three default roles are marked `is_builtin=1`, but remain editable and deletable.
- System prompts: `backend/routers/settings.py`
- System prompt presets: `backend/routers/settings.py`
- Embedding config: `backend/routers/settings.py`

## Skill Deletion Semantics

- Builtin Skills are no longer physically deleted from `backend/skills/builtin`.
- Deleting a builtin Skill writes a tombstone in the user skills directory and hides it immediately.
- Deleting a user override of a builtin Skill removes the override file and still keeps the builtin version hidden.
- Saving a builtin Skill as a user override clears the tombstone and makes the Skill visible again.

## Knowledge Service

- Knowledge import cleanup no longer double-resets the same import state during PPT ingest.
- Vector deletions now reuse a shared helper that escapes LanceDB string literals safely.
- Generic text ingestion, chunking, and vectorization are kept as one canonical path.

## Document Parsing Baseline

- Attachment text extraction and knowledge ingestion now share one canonical parser registry:
  - `backend/services/document_parsing/registry.py`
  - `backend/services/document_parsing/chunker.py`
  - `backend/services/document_parsing/prompt_render.py`
- `XLSX` parsing is no longer `values_only` flattening:
  - merged ranges are preserved
  - multi-row headers are converted into `header_path`
  - formulas are retained in structured table cells
- `DOCX` parsing is block-order aware:
  - headings, paragraphs, and tables keep source order
  - tables are emitted as structured table models instead of plain text only
- `PDF` parsing is now layout-aware first, plain-text fallback second:
  - PyMuPDF text blocks are classified into title / heading / paragraph / list-item
  - table detection is attempted when PyMuPDF is available
  - scanned pages can fall back to OCR when OCR dependencies are available
- `Image` parsing is no longer placeholder-only:
  - image metadata is extracted when Pillow is available
  - OCR is attempted through the shared OCR utilities when pytesseract + Tesseract are available
- OCR is now shared across image and scanned PDF parsing:
  - OCR text is segmented into structured blocks
  - OCR layout can be heuristically converted into simple tables

## Knowledge Chunk Metadata

- `knowledge_chunks` now stores `metadata_json` in SQLite.
- Search results may include richer locator fields such as:
  - `sheet`
  - `page`
  - `row_start` / `row_end`
  - `story`
  - `source`
  - `ocr_segment_index`
  - `table_title`
- LanceDB vector search now normalizes the same locator metadata back into search results where available.

## Citation Rendering

- Context citations are no longer limited to file name + chunk index.
- The frontend now surfaces locator badges for structured retrieval hits in:
  - `src/components/chat/MessageBubble.tsx`
  - `src/components/layout/ContextPanel.tsx`
- Typical visible locator chips now include:
  - worksheet name
  - row range
  - OCR segment number
  - table title
  - chunk number

## Chat Responsiveness UX Baseline

- Chat SSE no longer waits silently for the first model token before the UI gets feedback.
- `backend/routers/chat.py` now emits lightweight `status` SSE events before normal token chunks:
  - `queued`
  - `retrieving`
  - `calling_model`
  - `streaming`
- The frontend consumes these status events in `src/services/api.ts` and stores them on message metadata via `src/components/chat/ChatArea.tsx`.
- Assistant placeholder bubbles in `src/components/chat/MessageBubble.tsx` now show explicit progress states instead of a blank white box:
  - preparing the answer
  - retrieving context
  - calling the model
  - streaming the answer

## Attachment Analysis Fast-Path

- Very short small-talk queries and obvious short file-analysis queries no longer always pay an extra retrieval-planner LLM round-trip.
- `backend/services/retrieval_planner.py` now short-circuits to heuristic fallback for:
  - small talk / no-retrieval queries
  - short, single-surface file-analysis prompts such as “请分析这份文件的内容”
- This change is intended to reduce time-to-first-feedback, especially for greetings and simple attachment analysis requests.
- Attachment context sent from `src/components/chat/ChatArea.tsx` is now compacted when files are very large:
  - keep front / middle / tail excerpts
  - preserve the fact that truncation happened
  - avoid sending the full raw attachment text when that would significantly delay first token latency

## Attachment Analysis Preview

- Before the assistant starts streaming actual answer text, the frontend may now show a lightweight analysis preview card for attachment-heavy requests.
- Preview content is stored in message metadata as `generationPreview`.
- The preview is intentionally UI-only:
  - it does not alter model output
  - it disappears once real content starts streaming

## Realtime Markdown Rendering

- Assistant markdown is no longer rendered only after the full response completes.
- Streaming assistant responses now render through `src/components/chat/RichMarkdown.tsx` in real time.
- `RichMarkdown` now uses `useDeferredValue` for streaming content so markdown updates stay lower-priority than urgent UI work.
- Markdown renderer configuration is hoisted and reused instead of being recreated on every streaming update.

## Message Copy UX

- Copy actions are now available on both user messages and assistant messages.
- The copy affordance was restyled to be lower-contrast and less visually dominant:
  - icon-only
  - inside the message bubble
  - low emphasis until hover/focus
- Current implementation lives in `src/components/chat/MessageBubble.tsx`.

## Knowhow Routing in Chat

- Chat-side knowhow retrieval no longer does a flat all-rules keyword sweep only.
- `backend/services/knowhow_router.py` now adds a dedicated Phase 1 routing layer for knowhow:
  - skip small talk and obvious non-rule document-analysis prompts
  - route rule-oriented questions into the most likely knowhow categories first
  - use category-scoped rule scoring instead of mixing the whole rule library together
- The first gate is now effectively LLM-first for non-trivial queries when runtime LLM config is available:
  - whether knowhow is needed at all
  - which candidate categories are most relevant
- Heuristic routing is still kept as fallback when the runtime LLM is unavailable, and direct rule-text scoring now backstops weak category-profile matches.
- `backend/routers/chat.py` now passes runtime planner settings into `context_assembler.assemble(...)`, so chat retrieval planning and knowhow routing can both use LLM intent judgment when configured.
- `backend/services/context_assembler.py` still remains the single integration point, but its knowhow path now delegates actual routing to `knowhow_router` before prompt injection.
- Chat auto-retrieval still depends on a valid `role_id`; requests without `role_id` do not enable `knowledge/knowhow` surfaces.
- Latest in-process integration check on a fresh runtime confirmed:
  - `/api/knowhow/stats` returns a non-empty category list again for default rules
  - chat with `role_id="copilot"` produced `knowledge_count=1` and `knowhow_count=3` in `context_metadata`

## Knowhow Phase 2 Baseline

- Knowhow is no longer modeled as only `category + rule_text + weight` for chat retrieval.
- `backend/services/storage.py` and `backend/services/knowhow_service.py` now support richer Phase 2 fields:
  - category profile metadata:
    - `description`
    - `aliases`
    - `example_queries`
    - `applies_to`
  - rule metadata:
    - `title`
    - `trigger_terms`
    - `exclude_terms`
    - `applies_when`
    - `not_applies_when`
    - `examples`
- `backend/routers/knowhow.py` now exposes these fields through rule CRUD plus `PUT /api/knowhow/categories/{name}/profile`.
- Chat-side knowhow retrieval now uses category profiles as actual routing inputs, not just category names.
- `backend/services/context_assembler.py` now passes knowhow category profiles into `knowhow_router.retrieve_rules(...)`.
- `backend/services/knowhow_router.py` now adds a bounded LLM rule-judge stage after heuristic recall:
  - route first
  - score only routed-category rules
  - optionally let the runtime LLM keep only the truly applicable subset
- When category profiles are temporarily unavailable, chat still falls back to rule-only scoring instead of failing knowhow retrieval entirely.
- Knowhow export now uses `schema_version = 2`.
- The current product direction keeps the operator UX minimal:
  - the form still centers on `category + rule_text (+ optional weight)`
  - `backend/services/knowhow_service.py` now auto-enriches hidden retrieval metadata on save/import
  - explicit operator-supplied fields still win, while blank fields are auto-derived
  - category profiles are refreshed automatically from saved rules instead of requiring a heavy manual editor
- Regression coverage was expanded for:
  - Phase 2 rule/category payload fields
  - category profile routing
  - LLM-based candidate rule pruning

## Embedding Runtime Baseline

- Knowledge semantic retrieval is only truly available when two things are both true:
  - knowledge chunks have already been vectorized into LanceDB
  - the runtime has usable embedding credentials
- Chat retrieval already had a runtime fallback for embedding configuration, but knowledge ingestion used to depend only on dedicated embedding settings.
- `backend/routers/knowledge.py` now falls back to the active LLM profile when dedicated embedding settings are empty, using `text-embedding-3-small` as the embedding model target.
- Knowledge stats now expose embedding visibility signals:
  - `embedding_configured`
  - `embedding_model`
  - `total_text_chunks`
  - `total_vector_chunks`
- Knowledge ingest results now expose chunk diagnostics:
  - `stored_chunks_count`
  - `vector_chunks_count`
  - `embedding_status`
- The frontend knowledge panel in `src/components/layout/ContextPanel.tsx` now surfaces text chunk count and current embedding configuration state, so the operator can quickly tell whether semantic retrieval is even expected to work.

## No-Embedding LLM Fallback

- When knowledge semantic retrieval has no vector results but runtime LLM credentials are available, the system now falls back to LLM-based reranking instead of stopping at plain keyword order.
- `backend/services/hybrid_search.py` now supports a fallback flow:
  - gather structured / keyword candidates first
  - if semantic retrieval is unavailable or empty
  - ask the runtime LLM to rerank and filter the candidate set
- This fallback is wired into both:
  - chat-side knowledge retrieval through `backend/services/context_assembler.py`
  - direct knowledge query API through `backend/routers/knowledge.py`
- The fallback is intentionally bounded:
  - it only reranks already recalled candidates
  - it does not ask the model to search the whole corpus blindly

## Role Naming

- Runtime chat and conversation APIs use `role_id` / `roleId` as the canonical role field.
- Legacy `mode` is only kept as a compatibility fallback when reading older payloads or databases.

## 用户管理与 RBAC

- 用户、用户组、资源授权已全部落地，见 `backend/services/storage.py`。
- 认证流程：`POST /api/auth/login` 返回 JWT Token，前端通过 `authStore` 持久化，后续请求全部由 `authFetch` 自动注入 `Authorization: Bearer <token>`。
- 所有 `/api/*` 端点（除 `/api/health` 和 `/api/auth/login`）已添加 `get_current_user` 依赖保护。
- 管理员接口额外验证 `system_role=="admin"`。
- 密码直接使用 `bcrypt` 库（`bcrypt.hashpw` / `bcrypt.checkpw`），未引入 `passlib`，避免 `AttributeError: module 'bcrypt' has no attribute '__about__'` 兼容性问题。
- 默认管理员账户：`admin` / `admin123`（首次启动时自动创建）。

### 待完善事项

- Knowledge / AI Role / Skill 创建/编辑 UI 中的可见性选择器（Private / Group / Public）尚未实现。
- 资源列表页尚未根据 Access Grants 过滤，待后续辭代。

## Verification Baseline

- Backend tests: `pytest backend/tests -q`
- Frontend build: `npm run build`
