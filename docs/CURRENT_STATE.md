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
