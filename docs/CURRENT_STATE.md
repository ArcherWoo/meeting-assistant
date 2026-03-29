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

## Role Naming

- Runtime chat and conversation APIs use `role_id` / `roleId` as the canonical role field.
- Legacy `mode` is only kept as a compatibility fallback when reading older payloads or databases.

## Verification Baseline

- Backend tests: `pytest backend/tests -q`
- Frontend build: `npm run build`
