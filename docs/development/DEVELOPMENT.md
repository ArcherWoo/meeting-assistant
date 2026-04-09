# Meeting Assistant — 开发总结文档

> **项目形态**：纯 Web 应用（Vite 前端 + Python FastAPI 后端）。Electron 桌面版已废弃。

## 1. 项目概述

**Meeting Assistant** 是一款面向专业用户的 AI 会议助手 Web 应用，核心功能包括：

- 智能对话：与大语言模型（LLM）进行多轮对话，支持会话历史持久化
- 文件附件：通过聊天输入框附加文件，文件文本作为上下文随消息发送给 LLM
- 知识库管理：将文件永久导入向量数据库（LanceDB），支持语义检索增强生成（RAG）
- 技能系统：预定义的会议场景技能（会议纪要、任务拆解等）
- Agent 模式：自主完成多步任务的智能代理

---

## 2. 技术栈

- 前端：React + Vite + TypeScript + Zustand + Tailwind CSS
- 后端：FastAPI + SQLite + aiosqlite
- 知识检索：LanceDB + Embedding （可降级）
- 运行时规划：Planner + Context Assembler + Knowhow Router

---

## 3. 最新一轮：无 Embedding 的 LLM 重排 Fallback

- `backend/services/hybrid_search.py` 现在能接收运行时 LLM 配置，并在语义检索没有结果时走一层有界的 LLM 重排。
- 这条 fallback 不会替代候选召回：
  - 仍然先走 SQLite 结构化/关键词召回
  - LLM 只负责对候选集做重排和过滤
- `backend/services/context_assembler.py` 现在会把 planner settings 继续传给知识检索，让 chat 端也能用上这层 fallback。
- `backend/routers/knowledge.py` 同样会把运行时 LLM 配置传给直接知识查询接口，保持 API 和 chat 行为一致。
- 这一轮新增回归：
  - `backend/tests/test_knowledge_service.py`
  - `backend/tests/test_retrieval_planner.py`

---
## 4. 核心模块说明

```
Meeting Assistant/
├── backend/
│   ├── main.py            # FastAPI 应用入口，注册所有路由
│   ├── routers/
│   │   ├── knowledge.py   # /api/knowledge/* 端点（extract-text、ingest、imports、stats）
│   │   ├── chat.py        # /api/chat/stream 流式对话
│   │   ├── skills.py      # /api/skills 技能管理
│   │   ├── knowhow.py     # /api/knowhow 规则管理
│   │   └── agent.py       # /api/agent/execute Agent 执行
│   └── services/
│       └── knowledge_service.py  # 文本提取、知识库导入、CRUD 逻辑
├── src/
│   ├── main.tsx           # React 入口
│   ├── services/api.ts    # 所有 HTTP/SSE 调用封装
│   ├── stores/
│   │   ├── chatStore.ts   # 多会话状态 + 后端数据库同步缓存
│   │   └── appStore.ts    # 全局应用状态（后端连接状态等）
│   └── components/
│       ├── chat/
│       │   ├── ChatArea.tsx   # 消息列表、handleSend、流式渲染
│       │   └── ChatInput.tsx  # 输入框、📎 附件模式、文本提取
│       └── layout/
│           └── ContextPanel.tsx  # 右侧面板：知识库统计、导入、删除
├── package.json
└── vite.config.ts
```

---

## 5. 角色系统与状态管理

### 5.1 动态角色（Role）架构

应用已从旧的三模式硬编码（`copilot / builder / agent`）迁移至**数据库驱动的动态角色系统**。

| 层级 | 位置 | 说明 |
|------|------|------|
| **数据库** | `backend/services/storage.py` → `roles` 表 | 角色持久化存储，支持 CRUD |
| **后端 API** | `backend/routers/settings.py` `/settings/roles/*` | GET / POST / PUT / DELETE 角色端点 |
| **前端 API** | `src/services/api.ts` `listRoles / createRole / updateRole / deleteRole` | HTTP 封装 |
| **全局状态** | `src/stores/appStore.ts` `roles: Role[]` + `currentRoleId: string` | Zustand store，持久化 UI/LLM 配置 |
| **初始化** | `src/main.tsx` `initBackend()` | 启动时调用 `listRoles()` 并写入 store，同步设置 `rolesLoaded = true` |

**角色数据结构**（`src/types/index.ts`）：
```typescript
interface Role {
  id: string;            // 唯一标识（如 "copilot"、"my-role-xyz"）
  name: string;          // 显示名称
  icon: string;          // emoji 图标
  description: string;
  system_prompt: string; // 该角色的系统提示词
  capabilities: string[];// 能力列表（如 ["rag"]）
  is_builtin: number;    // 0 = 用户创建，1 = 默认内置角色（可编辑、可删除）
  sort_order: number;
}
```

### 5.2 状态管理规范

**`appStore`**（`src/stores/appStore.ts`）管理：
- 角色列表 `roles`、当前角色 `currentRoleId`、`rolesLoaded` 加载标志
- LLM 配置 `llmConfigs / activeLLMConfigId`
- 主题、侧边栏折叠、Context Panel 可见性等 UI 状态

**`chatStore`**（`src/stores/chatStore.ts`）管理：
- 对话列表 `conversations`、活跃对话 `activeConversationId`
- 消息列表 `messages`、流式状态 `isStreaming`
- 通过 `/api/chat/state`、`/api/conversations/*`、`/api/messages/*` 与后端 SQLite 同步；不再把 localStorage 作为聊天真相源

### 5.3 会话持久化现状

- 当前聊天会话与消息统一持久化到后端 SQLite（`backend/services/storage.py`）。
- 前端 `chatStore` 仅保存运行时状态、流式输出状态和当前已加载数据。
- `localStorage` 不再承担会话历史真相源职责；保留持久化的是 `appStore` 中的 UI/LLM 配置。

---

## 6. 已知问题与限制

| 问题 | 说明 |
|------|------|
| LanceDB 未安装 | 向量检索（RAG）不可用；知识库只存元数据，无法语义检索 |
| PDF/Word/Excel 解析 | 依赖 PyMuPDF / python-docx / openpyxl，未安装则相应格式无法解析 |
| 知识库向量搜索 | 仅当当前角色 `capabilities` 包含 `rag` 时才会触发检索；若缺少 Embedding/LanceDB 能力则自动降级 |

---

## 7. 本地开发指南

### 开发端口约定

为避免本地开发时前后端端口冲突，当前约定如下：

- 后端开发端口：`5173`
- 前端开发端口：`4173`
- 前端开发地址：`http://localhost:4173`
- 后端开发地址：`http://127.0.0.1:5173`
- 前端通过 Vite 代理把 `/api` 请求转发到后端 `5173`

补充说明：

- `start.py` 会同时启动后端 `5173` 和前端 `4173`

## 2026-04-09 启动与部署收敛

这轮主要收口了开发启动、Windows 生产部署和生产停机体验。

### 开发启动

- `start.py` 现在是统一开发入口
- 成功后会输出 `智枢前端` 和 `后端接口` 的本机地址、局域网地址
- 输出会优先带出 `192.168.*` 这类更常用的局域网地址

### Windows 生产部署

- `deploy.ps1` 现在不只是启动应用，还会在检测到已安装 Nginx 时自动接管 Nginx
- 自动化范围包括：
  - 复制 rendered 配置
  - 接入 `nginx.conf`
  - 执行 `nginx -t`
  - 启动或重载 Nginx
  - 注册 `MeetingAssistantNginx` 开机任务

如果 Nginx 不在常见目录，可以通过 `MEETING_ASSISTANT_NGINX_HOME` 指定目录。

### 生产优雅关闭

为避免直接杀进程导致端口残留，生产环境新增正式停机入口：

- Windows：`.\deploy.ps1 -Stop`
- Windows 应用和 Nginx 一起停：`.\deploy.ps1 -Stop -StopNginx`
- Linux：`./deploy.sh --stop`
- Linux 应用和 Nginx 一起停：`./deploy.sh --stop --stop-nginx`

Windows 下的实现不是硬停计划任务，而是通过运行时控制目录下发停止标记，让 `service_runner` 主动收尾退出。

## 2026-04-09 生产部署链路补强

这轮继续把“公司内网镜像 + 一键部署”这条链路收紧了。

### 生产依赖准备逻辑

- `deploy/deploy.py` 不再强制 fresh venv 后整包安装 `backend/requirements.txt`
- 现在会优先复用当前 Python 环境里已经可用的包
- 只会安装真正缺失的后端依赖
- 如果公司镜像缺少精确版本，会自动回退尝试可用版本

### 自动探测与回填

- `deploy/common.py` 现在会自动读取：
  - `PIP_INDEX_URL`
  - `PIP_EXTRA_INDEX_URL`
  - `PIP_TRUSTED_HOST`
  - `PIP_FIND_LINKS`
  - `PIP_NO_INDEX`
- 也会调用 `python -m pip config list` 做补充探测
- 首次生成 `deploy/server.env` 时会自动带出这些值
- 如果是旧版 `deploy/server.env`，也会自动回填空白镜像字段
- 旧版 `.server-venv` 如果没启用 `system-site-packages`，会自动重建

### 入口脚本

- 新增 Windows CMD 入口：`deploy.bat`
- `deploy.sh` 补齐了：
  - `--prepare`
  - `--foreground`
  - `--stop`
  - `--stop-nginx`

### 本轮验证

- `python -m py_compile deploy/common.py deploy/deploy.py deploy/service_runner.py backend/tests/test_deploy_common.py`
- `pytest backend/tests/test_deploy_common.py -q`
- `pytest backend/tests/test_service_runner.py -q`
- `pytest backend/tests -q` -> `160 passed`
- 生产部署时不再区分这两个端口，而是默认只暴露一个应用端口 `5173`

### 手动分别启动

**后端**（开发模式，支持热重载）：
```bash
cd backend
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 5173 --reload
```

**前端**（Vite 开发服务器）：
```bash
npm run dev
```

启动后访问：

```text
http://localhost:4173
```

### 端口说明

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI 后端 | 5173 | 固定端口 |
| Vite 前端 | 4173 | 仅开发环境使用，浏览器访问 `http://localhost:4173` |

### 数据存储路径

```
~/.meeting-assistant/
├── knowledge.db    # SQLite 元数据
└── vectors/        # LanceDB 向量数据
```

---

## 8. 注意事项

> ⚠️ **绝不提交 API Key**：确保 `.env` 文件在 `.gitignore` 中，密钥通过环境变量读取，不硬编码。

---

## 9. Phase 1（Orchestrator 层）深度复查与交接记录

> 本节作为当前阶段的**唯一交接上下文依据**。结论以实际代码复核与构建/测试结果为准，不以口头判断代替。

### 9.1 当前总体结论

- 本轮 Phase 1 主链路改造已经落地，包含：RAG/Know-how/Skill 上下文组装、动态 token 预算、SSE 尾事件注入、Copilot 内联 Skill 推荐。
- 当前代码已通过：
  - 后端测试：`py -3.13 -m pytest backend/tests -q` → `8 passed`
- **但不能判定为“已经完全没问题”**。深度复查后，仍确认存在若干**必须继续修复**的问题，其中最高优先级问题仍然直接影响 **LLM 回答质量**。
- 当前状态应定义为：**Phase 1 主方案已实现，但尚未达到“质量审查收口”标准，必须继续完成剩余问题修复后才能收尾。**

### 9.2 本轮已完成项

#### 8.2.1 后端：上下文组装与预算控制

- `backend/services/context_assembler.py`
  - 已实现 `AssembledContext.fit_to_budget(max_chars)`：按**完整条目**裁剪上下文，而不是拼接后硬截断。
  - 已实现 `to_prompt_suffix()` 与预算裁剪联动，避免把单条知识/规则截断成残缺文本。
  - 已接入知识库结果、Know-how 规则、Skill 匹配结果三类上下文源。

- `backend/routers/chat.py`
  - 已新增 `_assemble_context()`：在 chat 路由中独立执行 copilot 场景的上下文组装。
  - 已新增 `_calculate_context_budget_chars()`：根据模型窗口、已有消息长度、输出预留量动态计算可注入字符预算。
  - 已将裁剪后的上下文追加到 system prompt，避免固定 3000 字符硬限制。

#### 8.2.2 后端：SSE 元数据尾注入

- `backend/routers/chat.py`
  - 已新增 `_stream_with_metadata()`。
  - 已确认 `context_metadata` 与 `skill_suggestion` 事件在 `data: [DONE]` **之前**注入，满足既定协议顺序要求。
  - 已补充真实流样例与字段说明，见 `docs/chat-completions-context-example.sse` 与 `docs/SSE_CONTEXT_METADATA.md`。

#### 8.2.3 后端：短查询 embedding 保护

- `backend/services/hybrid_search.py`
  - 已加入“极短查询跳过 embedding 调用”的保护逻辑，避免明显无意义的 embedding 请求。
  - 但当前阈值仍未调优到最终合理状态，详见“未修复问题”。

#### 8.2.4 前端：SSE 解析与内联 Skill 推荐

- `src/services/api.ts`
  - 已能解析后端尾部注入的 `context_metadata` 与 `skill_suggestion` 事件。
  - 前端现已消费 `schema_version`、`truncated`、`retrieved_*`、`matched_keywords` 等增强字段。

- `src/components/chat/ChatArea.tsx`
  - 已在 Copilot 聊天区内实现内联 Skill 推荐条。
  - 用户可在当前对话中点击“应用”，将推荐话术预填充到输入框，不会强制跳转到 Agent 面板。

- `src/components/chat/MessageBubble.tsx`
  - citation 卡片已收敛为固定的“文件名/来源 + 位置 + 摘要”视觉层，能稳定展示文件名、页码/片段位置和摘要内容。

- `src/components/chat/ChatInput.tsx`
  - 已支持外部 `prefillText` 注入并自动写入输入框，形成 Skill 推荐 → 输入框预填 → 用户确认发送的闭环。

### 9.3 已验证项

#### 8.3.1 构建验证

- 命令：`npm run build`
- 结果：**通过**
- 说明：Vite 构建完成，无 TypeScript 编译错误。
- 备注：构建过程中存在一个 `MODULE_TYPELESS_PACKAGE_JSON` 警告（`postcss.config.js` 被按 ES module 重解析），当前**不阻塞功能**，暂不列入本轮必须修复项。

#### 8.3.2 后端测试验证

- 命令：`py -3.13 -m pytest backend/tests -q`
- 结果：**通过**，`8 passed in 0.66s`
- 说明：说明本轮改动未破坏当前后端既有单元测试覆盖范围。

#### 8.3.3 已明确满足设计目标的点

- **Token 预算策略**：已从“拼接后硬截断”改为“按完整条目注入 + 超预算即停止”。
- **SSE 顺序要求**：`context_metadata` / `skill_suggestion` 已在 `[DONE]` 前发送。
- **Skill 交互闭环**：已采用 Copilot 内联推荐条，而不是强制跳转 Agent 面板。
- **多对话流式隔离**：`ChatArea.tsx` 中 `AbortController`、streaming 状态与 Skill 推荐已按 `conversationId` 进行隔离管理。

### 9.4 本轮深度复查结论

- 本轮复查覆盖了以下关键文件与调用链：
  - `backend/services/hybrid_search.py`
  - `backend/services/context_assembler.py`
  - `backend/routers/chat.py`
  - `src/services/api.ts`
  - `src/components/chat/ChatArea.tsx`
  - `src/components/chat/ChatInput.tsx`
  - 关联核对：`src/types/index.ts`、`src/stores/chatStore.ts`
- 结论：**已确认存在 3 个仍需继续修复的问题**。这些问题并非编译级错误，而是会影响回答质量、召回率、状态语义、或前端能力溯源闭环的一致性问题。

### 9.5 已发现但未修复的问题（必须继续处理）

#### P0 — Know-how 仍然是“全量活跃规则注入”，存在上下文污染风险

- **问题是什么**
  - 当前 `backend/services/context_assembler.py::_get_knowhow_rules()` 直接返回全部活跃规则：`knowhow_service.list_rules(active_only=True)`。
  - 在 `AssembledContext.fit_to_budget()` 中，Know-how 规则又被放在首个预算段优先注入。

- **为什么重要**
  - 这会让与当前 query 无关的规则优先占用 prompt 预算。
  - 在规则量增大后，会直接稀释真正相关的知识库命中内容，伤害 LLM 回答质量。

- **会影响什么**
  - 影响 RAG 召回后的有效上下文占比。
  - 影响模型对用户问题的聚焦度。
  - 影响后续系统扩展：规则越多，污染越严重。

- **涉及文件 / 函数**
  - `backend/services/context_assembler.py::_get_knowhow_rules`
  - `backend/services/context_assembler.py::AssembledContext.fit_to_budget`
  - `backend/services/context_assembler.py::to_prompt_suffix`

- **建议怎么修**
  - 保留“完整条目注入”原则不变。
  - 在 `_get_knowhow_rules(query)` 中增加**基于 query 的相关性过滤/排序**，至少做到：
    - 先筛掉明显无关规则；
    - 再按相关性 + 权重排序；
    - 只把相关规则交给预算裁剪层。
  - 不要回退到“全量注入 + 靠预算硬挡”的思路。

- **优先级**：`P0`

#### P1 — 语义检索短查询阈值过高，可能损失中文短查询召回

- **问题是什么**
  - 当前 `backend/services/hybrid_search.py::_semantic_search()` 仍使用 `if len(query.strip()) < 4: return []`。

- **为什么重要**
  - 中文里 2~3 个字的查询经常已经具备明确语义，例如“采购价”“电脑”“运费”“联想”等。
  - `< 4` 会把这些本应可检索的 query 直接排除在 embedding 之外，导致语义召回损失。

- **会影响什么**
  - 影响知识库检索召回率。
  - 进而影响回答是否能拿到正确的 RAG 证据。

- **涉及文件 / 函数**
  - `backend/services/hybrid_search.py::_semantic_search`

- **建议怎么修**
  - 将阈值从 `< 4` 下调到 `< 2`。
  - 仅对空串或 1 字符噪声查询跳过 embedding。
  - 保留结构化检索作为兜底，但不要让阈值过高损失语义召回。

- **优先级**：`P1`

#### 已修复 — Skill 推荐已与预算裁剪解耦，避免“匹配到了却不下发推荐”

- **问题是什么**
  - 旧版本中，`skill_suggestion` 事件错误地依赖裁剪后的 prompt 上下文。
  - 当 `matched_skills` 因预算被裁掉时，即使原始检索命中了 Skill，前端也收不到推荐。

- **当前状态**
  - `backend/routers/chat.py` 现在区分“原始检索上下文”和“实际注入 prompt 的上下文”。
  - `context_metadata.sources` 默认表示真正注入的上下文。
  - 新增 `truncated` / `retrieved_*` 字段，用于描述裁剪前的原始结果。
  - `skill_suggestion` 改为基于原始匹配结果发送，不再受 prompt 预算裁剪影响。
  - `skill_suggestion` 还新增 `matched_keywords` 字段，便于前端后续展示命中依据。

- **结果**
  - Copilot 内联 Skill 推荐不会再因 prompt 预算打满而丢失。
  - 后端 SSE 协议同时保留了“实际注入”和“原始检索”两套信息，便于前端按需扩展。

- **状态标记**：`Closed`

#### P1 — Abort 被当成 Done 处理，状态语义错误

- **问题是什么**
  - 当前 `src/services/api.ts::streamChat()` 中，`AbortError` 会执行 `onDone()`。
  - 同时在流正常结束但未收到真实 `[DONE]` 时，也可能因为 `if (!finished) onDone()` 触发结束回调。

- **为什么重要**
  - “用户中止”与“模型正常完成”不是同一语义。
  - 当前 `ChatArea.tsx` 的 `onDone` 中包含自动命名等后置逻辑；中止时执行这些逻辑会污染状态。

- **会影响什么**
  - 会导致被中断回答被当成完整回答处理。
  - 会错误触发自动标题生成等后续动作。

- **涉及文件 / 函数**
  - `src/services/api.ts::streamChat`
  - `src/components/chat/ChatArea.tsx` 中 `streamChat(..., onDone, ...)` 的完成后逻辑

- **建议怎么修**
  - `AbortError` 不应调用 `onDone()`；应静默返回，或增加独立 `onAbort()` 回调。
  - `onDone()` 只在真实完成时触发：收到 `[DONE]`，或明确判定服务端已正常结束且协议完整。

- **优先级**：`P1`

#### 已修复 — `context_metadata` 已完成“注入 + 状态落库 + 消费展示”闭环

- **问题是什么**
  - 早期版本中，`context_metadata` 只停留在 SSE 协议层，尚未完成前端状态落库与 UI 展示闭环。
  - 这会让“能力溯源”停留在接口层，用户无法在 UI 上稳定看到引用来源。

- **当前状态**
  - `src/services/api.ts` 已解析 `context_metadata` / `skill_suggestion`。
  - `src/components/chat/ChatArea.tsx` 已将 `onMetadata` 绑定到当前 assistant 消息。
  - `src/types/index.ts::Message` 已具备 `metadata` 结构。
  - `src/stores/chatStore.ts` 已支持消息 metadata 更新与持久化。
  - `src/components/chat/MessageBubble.tsx` 已展示 source badge、summary 与 citation。
  - `src/components/layout/ContextPanel.tsx` 已消费当前对话最近一条 assistant 消息的 metadata，并在右侧面板展示“文件名/来源 + 位置 + 摘要”。

- **结果**
  - “能力溯源”现在已经完成协议、状态、消息 UI、右侧面板四层闭环。
  - 刷新页面后仍可保留相关 metadata。

- **状态标记**：`Closed`

### 9.6 下一步待办（必须继续执行）

1. **先修 P0：Know-how 相关性过滤**
   - 原因：这是当前最直接影响 LLM 回答质量的问题。
   - 目标：让 prompt 预算优先留给“与当前 query 真正相关”的规则与知识。

2. **再修短查询语义召回阈值**
   - 原因：这是第二个直接影响回答质量的问题，且改动小、收益明确。

3. **修复 Abort / Done 语义**
   - 原因：这是状态正确性问题，会影响自动命名与中止体验，但相对前两项对回答质量影响略低。

### 9.7 推荐处理顺序（含原因）

#### 第一优先序列：先保回答质量

1. `backend/services/context_assembler.py` — 修复 Know-how 全量注入
2. `backend/services/hybrid_search.py` — 将短查询阈值从 `< 4` 调整到 `< 2`

**原因**：这两项直接决定模型能否拿到“更准、更相关”的上下文，是当前最核心的质量瓶颈。

#### 第二优先序列：补协议与交互一致性

3. `src/services/api.ts` + `src/components/chat/ChatArea.tsx` — 修复 Abort 误判为 Done

**原因**：这是重要一致性问题，但优先级略低于回答质量与能力下发完整性。

### 9.8 后续实现时必须遵守的背景约束

- **LLM 回答质量优先**，不能为了简化实现而牺牲回答质量。
- **Token 预算必须按完整条目注入**，禁止回退到拼接后硬截断。
- **SSE metadata 必须在 `[DONE]` 前注入**，前后端协议顺序不可破坏。
- **Skill 推荐必须保持 Copilot 对话内联闭环**，不要强行跳转 Agent 面板。
- **模式与对话状态必须按 `conversationId` 隔离**，避免串线。
- 中文 token 预算仍按保守估算：**1 个汉字 ≈ 0.6 token**。
- 当前构建与测试已通过，但这**不等于**逻辑审查完成；后续改动仍需继续执行构建与测试验证。

### 9.9 当前残余风险（即使暂未列为最高优先级，也不能遗忘）

- 当前未进行真正的前端 UI 自动化/E2E 验证；`context_metadata` 的展示闭环虽已落地，但仍缺少自动化回归验证。
- `ChatArea.tsx` 当前 `prefillText` 是组件级单值状态，后续仍需复查是否存在跨对话误写或覆盖未发送草稿的风险。
- 当前已通过构建与后端测试，但并未因此证明所有 SSE 边界时序都已覆盖；后续修复 `Abort` 语义后应补一次针对流中止场景的验证。

### 9.10 交接结论

- **已经完成**：Phase 1 主链路功能改造与基础验证。
- **已经确认没回退的点**：构建可过、后端测试可过、SSE 元数据顺序正确、Skill 推荐保持对话内联、token 预算不再硬截断。
- **仍必须继续修复**：Know-how 相关性过滤、短查询语义召回阈值、Abort/Done 语义。
- **下次继续工作时，严格按 8.7 的顺序推进，不要重新做大范围排查。**
## 10. 文档解析与 OCR 新基线

### 10.1 统一解析架构

当前附件文本提取与知识库导入已经统一收敛到 `backend/services/document_parsing/`：

- `registry.py`：按扩展名分发 parser
- `models.py`：统一 IR，包含 `ParsedDocument / DocumentBlock / StructuredTable / TableCell`
- `chunker.py`：把 IR 转成知识库 chunks，并写入 `metadata_json`
- `prompt_render.py`：把结构化解析结果渲染成 LLM 可消费文本

这意味着：

- 附件模式与知识库导入不再各自维护一套解析逻辑
- 新格式能力只需要接一次 parser，即可同时服务两条链路
- chunk 的结构信息可以继续传递到检索、citation 与前端定位展示

### 10.2 格式能力现状

#### PPT / PPTX

- 保留现有专用解析器能力，并通过 `ppt_parser_adapter.py` 接入统一 IR
- 支持 slide、note、table 等结构块进入统一 chunking 流程

#### XLSX

- 使用 OOXML parser，不再是 `values_only=True` 文本摊平
- 当前会保留：
  - merged ranges
  - 多层表头
  - `header_path`
  - formula
  - sheet 级定位

#### DOCX

- 使用 OOXML parser，按块级顺序遍历
- 当前会保留：
  - heading / paragraph / table 原始顺序
  - 结构化表格
  - header style 等基础来源定位

#### PDF

- 优先使用 PyMuPDF 做 layout-aware 提取
- 会把文本块分类为：
  - `title`
  - `heading`
  - `paragraph`
  - `list_item`
- 可尝试提取 PDF 表格
- 若页面没有可提取文本与表格，会尝试把页面渲染成图片再走 OCR

#### Image

- 可提取图片元数据
- 可选执行 OCR
- 与 scanned PDF 共用同一套 OCR 工具和切块逻辑

### 10.3 OCR 能力边界

OCR 相关实现集中在 `backend/services/document_parsing/parsers/ocr_utils.py`：

- `extract_ocr_layout_from_image_bytes()`：读取 Tesseract OCR 结果与行布局
- `segment_ocr_text()`：把 OCR 文本切成标题 / 段落 / 列表块
- `build_ocr_structure()`：尝试从 OCR 行布局恢复简单表格

当前 OCR 表格恢复属于启发式方案，适合：

- 列间距比较稳定的报价表
- 规则二维表
- 扫描件中行列相对整齐的表格

当前不保证稳定处理：

- 复杂跨列跨行表
- 手写表格
- 倾斜严重或噪点较高的扫描件
- 表头层级非常复杂的 OCR 表格

### 10.4 检索定位与前端展示

`knowledge_chunks.metadata_json` 现在会保存 richer locator 信息，例如：

- `sheet`
- `page`
- `row_start / row_end`
- `story`
- `source`
- `ocr_segment_index`
- `table_title`

这些字段会沿链路进入：

- SQLite 关键词搜索结果
- LanceDB 语义检索归一化结果
- `context_assembler` citation
- 前端 `MessageBubble` 与 `ContextPanel` 的 locator badges

### 10.5 依赖说明

当前文档解析与 OCR 相关依赖为：

- `python-pptx`
- `PyMuPDF`
- `pypdf`
- `Pillow`
- `pytesseract`

运行时说明：

- 没有 `PyMuPDF` 时，PDF 会回退到 `pypdf`
- 没有 `Pillow + pytesseract + Tesseract` 时，OCR 会优雅降级，不阻断知识库导入或附件文本提取主流程

### 10.6 验证基线

本轮相关能力的最低验证要求：

- `pytest backend/tests -q`
- `npm run build`

新增重点覆盖：

- XLSX merged cells / header_path
- DOCX 段落与表格顺序
- scanned PDF OCR block segmentation
- OCR table recovery
- citation locator rich metadata
---

## 2026-04-07 开发补充记录：Know-how 权限收口与会话隐私调整

### 1. Chat 与 Know-how 权限链路

- 重新核查并确认了 `chat -> context_assembler -> knowhow_service -> storage/access_control` 这条链路已经打通。
- Chat 下 Know-how 的可见范围现在按当前登录用户计算，不再默认把规则库当成全局资源注入。
- 当前生效口径为：
  - 个人规则
  - 本组共享规则
  - 显式授权给当前用户的规则
  - 显式授权给当前用户组的规则
  - `public` 规则
  - 管理员全量

### 2. Know-how 管理作用域

- 组内 `can_manage_group_knowhow=1` 的用户具备“本组 Know-how manager”能力，但仅在本组作用域内生效。
- 组内 manager 支持双轨建规则：
  - 创建自己的个人规则
  - 创建共享给本组的 baseline 规则
- 分类管理权限已与作用域对齐：
  - 管理员管理全局分类
  - 组内 manager 只能管理本组共享规则实际使用到的分类
- 导入 / 导出也已按作用域收口：
  - 管理员可全量导入导出
  - 组内 manager 只能追加导入、导出本组规则
  - 导入去重按其可管理范围计算

### 3. Chat 命中闭环

- Chat 命中的 Know-how 规则现在会回写 `hit_count`。
- Know-how 引用元数据已增强，可携带：
  - 命中分类
  - 命中方式
  - 命中置信度
  - 命中原因
- “规则库问答”与“规则应用召回”已经分流：
  - 问规则库本身时，走规则库摘要
  - 问业务判断时，走规则召回
- 规则库摘要按当前用户可见范围实时生成，不再回答全库数字。

### 4. 会话隐私模型

- 会话列表和会话访问权限已统一调整为“仅本人可见 / 可操作”。
- 本次明确移除了管理员查看所有用户会话的默认行为。
- 当前统一口径：
  - 管理员只看自己的会话
  - 组内 manager 只看自己的会话
  - 普通用户只看自己的会话

### 5. 关键实现文件

- `backend/routers/chat.py`
- `backend/services/context_assembler.py`
- `backend/services/knowhow_service.py`
- `backend/services/knowhow_router.py`
- `backend/services/storage.py`
- `backend/services/access_control.py`
- `backend/routers/knowhow.py`
- `backend/routers/conversations.py`
- `backend/tests/test_auth_permissions.py`
- `backend/tests/test_conversations_router.py`

### 6. 本次验证结果

- `pytest backend/tests -q` -> `120 passed`
- 本次验证重点覆盖：
  - Chat 下 Know-how 权限作用域
  - 规则库统计问法的可见范围
  - 组内 manager 的规则 / 分类 / 导入导出作用域
  - 管理员仅可见自己的会话
  - 管理员不能访问他人会话消息
