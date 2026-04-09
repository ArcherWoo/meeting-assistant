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

## 2026-04-07 Chat / Know-how 权限与会话可见性

- Chat 链路现在会按当前登录用户过滤 Know-how，可见范围不再是全库默认开放。
- `backend/routers/chat.py` 会把当前登录用户传入 `context_assembler.assemble(...)`。
- `backend/services/context_assembler.py` 在拉取 Know-how 规则、分类和规则库摘要时，统一带上：
  - `user_id`
  - `group_id`
  - `is_admin`
- `backend/services/storage.py::list_knowhow_rules(...)` 当前生效的 Chat / 列表可见范围是：
  - 自己的个人规则
  - 自己所在用户组的共享规则
  - 显式授权给自己的规则
  - 显式授权给自己所在用户组的规则
  - `public` 授权规则
  - 管理员可见全部规则
- 因此，Chat 下 Know-how 的真实权限语义是“个人 / 本组共享 / 显式授权 / 管理员全量”。
- `backend/services/access_control.py` 已与 `storage.py` 的 Know-how 权限口径对齐：
  - 组共享规则由当前组内 `can_manage_group_knowhow=1` 的用户管理
  - 个人规则由 owner 管理
  - 管理员保留全量管理能力
- 组内 Know-how manager 现在支持双轨建规则：
  - 可创建个人专属规则
  - 可创建共享给本组的 baseline 规则
- 组内 Know-how manager 的分类管理与导入导出也已按作用域收口：
  - 管理员管理全局分类和全量导入导出
  - 组内 manager 只能管理本组共享规则实际使用到的分类
  - 组内 manager 只能追加导入、导出本组作用域内的规则
  - 导入去重按其可管理范围计算，不再拿全库静默去重
- Chat 命中 Know-how 后会真实回写 `hit_count`，后续排序可逐步反映真实使用热度。
- Chat 中的 Know-how 引用元数据已经增强，支持展示：
  - 命中分类
  - 命中方式
  - 命中置信度
  - 命中原因
- “规则库问答”和“规则应用召回”已经分流：
  - 询问“规则库里有多少条规则 / 有哪些分类”时，走规则库摘要分支
  - 规则库摘要按当前用户可见范围实时生成，不回答全库数字

## 2026-04-07 会话隐私口径

- 会话列表、会话详情、消息列表与消息读写，现在统一按“仅本人可见 / 可操作”处理。
- 不再存在“管理员默认可见所有人对话”的产品行为。
- 当前统一口径：
  - 管理员只看自己的会话
  - 组内 manager 只看自己的会话
  - 普通用户只看自己的会话
- `backend/routers/conversations.py` 已收口两处关键逻辑：
  - `GET /api/chat/state` 只返回当前用户自己的会话
  - 会话访问校验不再给管理员开全量直通
- 这意味着前端新建对话、左侧会话列表、消息加载都会天然遵循“仅本人会话”的可见性。

## 2026-04-07 回归验证

- Know-how Chat 权限回归已补齐：
  - 组用户在 Chat 中只能命中自己可见的 Know-how
  - 规则库统计问法返回的是当前可见范围的规则数
- 会话隐私回归已补齐：
  - 管理员的聊天状态只返回自己创建的会话
  - 管理员不能读取其他用户会话消息
- 当前通过的回归基线：
  - `pytest backend/tests -q` -> `120 passed`

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
## 2026-04-09 启动与部署基线

当前开发启动和生产部署的入口已经统一收敛：

- 开发环境入口：`python start.py`
- Windows 生产入口：`.\deploy.ps1`
- Windows CMD 入口：`deploy.bat`
- Linux 生产入口：`./deploy.sh`

### 开发环境

`start.py` 当前具备这些行为：

- 自动检查 Python / Node.js
- 自动安装依赖
- 自动清理旧的开发进程
- 自动等待前后端服务就绪
- 成功后输出 `智枢前端` 和 `后端接口` 的本机地址、局域网地址
- 失败时输出关键日志尾部

### Windows 生产部署

`deploy.ps1` 当前已经支持：

- 自动准备生产虚拟环境和 `deploy/server.env`
- 自动构建前端并启动应用服务
- 自动注册 `MeetingAssistant` 计划任务做开机自启
- 如果已经安装 Nginx，则自动：
  - 发现 `nginx.exe`
  - 复制 rendered 配置到 `conf/meeting-assistant.conf`
  - 自动把 `include meeting-assistant.conf;` 接入主 `nginx.conf`
  - 执行 `nginx -t`
  - 启动或重载 Nginx
  - 注册 `MeetingAssistantNginx` 计划任务

说明：

- Nginx 本体不会随项目一起安装，仍需在 Windows Server 上预先安装
- 但装好后，`deploy.ps1` 已经可以自动把它接进整条部署链路
- 如果运维习惯使用 `cmd.exe`，现在可以直接运行 `deploy.bat`，它会自动转调 `deploy.ps1`

### 生产依赖准备自动化

生产部署的依赖准备逻辑现在已经与 `start.py` 对齐：

- `.server-venv` 默认启用 `system-site-packages`
- 优先复用当前 Python 环境里已经可用的包
- 只安装真正缺失的后端依赖
- 对公司内部镜像缺少精确版本的场景，允许自动回退到可用版本
- 如果机器上残留旧版 `.server-venv` 且没有启用 `system-site-packages`，脚本会自动重建
- 脚本会自动读取当前机器的 pip 环境变量和 `pip config list`
- 首次创建或后续回填 `deploy/server.env` 时，会自动补齐镜像相关字段

### Linux 生产入口

`deploy.sh` 当前也已经补齐了明确的命令入口：

- `./deploy.sh`
- `./deploy.sh --prepare`
- `./deploy.sh --foreground`
- `./deploy.sh --stop`
- `./deploy.sh --stop --stop-nginx`

### 生产优雅关闭

生产环境现在也有正式的优雅关闭入口，不再建议直接杀进程或只停计划任务。

Windows：

- `.\deploy.ps1 -Stop`
- `.\deploy.ps1 -Stop -StopNginx`

Linux：

- `./deploy.sh --stop`
- `./deploy.sh --stop --stop-nginx`

其中 Windows 关闭链路当前是：

- 脚本写入运行时停止标记
- `service_runner` 检测到后主动停止所有子实例
- 应用健康检查真正下线后再返回

这条链路比直接结束 `python.exe` 或 `Stop-ScheduledTask` 更安全，更不容易留下端口占用。
