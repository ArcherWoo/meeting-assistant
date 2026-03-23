# Meeting Assistant — 开发总结文档

> **项目形态**：纯 Web 应用（Vite 前端 + Python FastAPI 后端）。Electron 桌面版已废弃。

## 1. 项目概述

**Meeting Assistant** 是一款面向专业用户的 AI 会议助手 Web 应用，核心功能包括：

- 💬 **智能对话**：与大语言模型（LLM）进行多轮对话，支持会话历史持久化
- 📎 **文件附件**：通过聊天输入框附加文件，文件文本作为上下文随消息发送给 LLM
- 📚 **知识库管理**：将文件永久导入向量数据库（LanceDB），支持语义检索增强生成（RAG）
- 🛠️ **技能系统**：预定义的会议场景技能（会议纪要、任务拆解等）
- 🤖 **Agent 模式**：自主完成多步任务的智能代理

---

## 2. 技术栈

### 前端
| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18 | UI 框架 |
| TypeScript | 5 | 类型安全 |
| Vite | 6 | 构建工具 / 开发服务器 |
| Zustand | 最新 | 全局状态管理（含 localStorage 持久化） |
| Tailwind CSS | 3 | 样式框架 |

### 后端
| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.115 | Web 框架 |
| Uvicorn | 0.32 | ASGI 服务器 |
| SQLite + aiosqlite | — | 知识库元数据存储 |
| LanceDB | 可选 | 向量数据库（RAG 检索） |
| python-pptx | 1.0 | PPT 解析 |
| PyMuPDF (fitz) | 可选 | PDF 解析 |
| python-docx | 可选 | Word 文档解析 |
| openpyxl | 可选 | Excel 解析 |

### AI
- 外部 LLM API（OpenAI 兼容格式，可配置 base_url / model / api_key）
- Embedding 模型（用于知识库向量化，需 LanceDB 支持）

---

## 3. 开发阶段总结

### Phase 1：基础架构
- Vite + React 前端骨架搭建
- FastAPI 后端基础框架（固定端口 8765）
- 聊天界面：多会话管理、消息气泡、流式 SSE 响应
- PPT 解析端点（`/api/ppt/parse`）

### Phase 2：RAG 与知识管理
- 知识库导入管道：文件解析 → LLM 结构化 → SQLite 元数据 → 分块 → 向量化 → LanceDB
- 知识库统计、导入记录查询与删除（`/api/knowledge/*`）
- 技能系统（`/api/skills`）和 Know-how 规则（`/api/knowhow`）
- Agent 模式（`/api/agent/execute`，SSE 事件流）

### 本次迭代：交互优化与工程完善
- **📎 按钮重构**：从「直接导入知识库」改为「附件模式」——提取文本作为上下文随消息发送
- **`/api/knowledge/extract-text`**：新增仅提取文本（不入库）的轻量端点
- **对话历史持久化**：Zustand `persist` 中间件 + localStorage，刷新不丢数据
- **Context Panel 增强**：知识库管理 UI（导入文件、查看列表、删除记录）
- **`start.py`**：一键启动脚本，含环境检测与依赖自动安装

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
│   │   ├── chatStore.ts   # 多会话状态 + localStorage 持久化
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

## 5. 已知问题与限制

| 问题 | 说明 |
|------|------|
| LanceDB 未安装 | 向量检索（RAG）不可用；知识库只存元数据，无法语义检索 |
| PDF/Word/Excel 解析 | 依赖 PyMuPDF / python-docx / openpyxl，未安装则相应格式无法解析 |
| 知识库向量搜索 | 当前 RAG 管道尚未完整接入对话（检索结果未自动注入 prompt） |

---

## 6. 本地开发指南

### 手动分别启动

**后端**（开发模式，支持热重载）：
```bash
cd backend
py -3.13 -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

**前端**（Vite 开发服务器）：
```bash
npm run dev
```

### 端口说明

| 服务 | 端口 | 说明 |
|------|------|------|
| FastAPI 后端 | 8765 | 固定端口 |
| Vite 前端 | 5173 | 浏览器访问 `http://localhost:5173` |

### 数据存储路径

```
~/.meeting-assistant/
├── knowledge.db    # SQLite 元数据
└── vectors/        # LanceDB 向量数据
```

---

## 7. 注意事项

> ⚠️ **绝不提交 API Key**：确保 `.env` 文件在 `.gitignore` 中，密钥通过环境变量读取，不硬编码。

---

## 8. Phase 1（Orchestrator 层）深度复查与交接记录

> 本节作为当前阶段的**唯一交接上下文依据**。结论以实际代码复核与构建/测试结果为准，不以口头判断代替。

### 8.1 当前总体结论

- 本轮 Phase 1 主链路改造已经落地，包含：RAG/Know-how/Skill 上下文组装、动态 token 预算、SSE 尾事件注入、Copilot 内联 Skill 推荐。
- 当前代码已通过：
  - 后端测试：`py -3.13 -m pytest backend/tests -q` → `8 passed`
- **但不能判定为“已经完全没问题”**。深度复查后，仍确认存在若干**必须继续修复**的问题，其中最高优先级问题仍然直接影响 **LLM 回答质量**。
- 当前状态应定义为：**Phase 1 主方案已实现，但尚未达到“质量审查收口”标准，必须继续完成剩余问题修复后才能收尾。**

### 8.2 本轮已完成项

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

#### 8.2.3 后端：短查询 embedding 保护

- `backend/services/hybrid_search.py`
  - 已加入“极短查询跳过 embedding 调用”的保护逻辑，避免明显无意义的 embedding 请求。
  - 但当前阈值仍未调优到最终合理状态，详见“未修复问题”。

#### 8.2.4 前端：SSE 解析与内联 Skill 推荐

- `src/services/api.ts`
  - 已能解析后端尾部注入的 `context_metadata` 与 `skill_suggestion` 事件。

- `src/components/chat/ChatArea.tsx`
  - 已在 Copilot 聊天区内实现内联 Skill 推荐条。
  - 用户可在当前对话中点击“应用”，将推荐话术预填充到输入框，不会强制跳转到 Agent 面板。

- `src/components/chat/ChatInput.tsx`
  - 已支持外部 `prefillText` 注入并自动写入输入框，形成 Skill 推荐 → 输入框预填 → 用户确认发送的闭环。

### 8.3 已验证项

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

### 8.4 本轮深度复查结论

- 本轮复查覆盖了以下关键文件与调用链：
  - `backend/services/hybrid_search.py`
  - `backend/services/context_assembler.py`
  - `backend/routers/chat.py`
  - `src/services/api.ts`
  - `src/components/chat/ChatArea.tsx`
  - `src/components/chat/ChatInput.tsx`
  - 关联核对：`src/types/index.ts`、`src/stores/chatStore.ts`
- 结论：**已确认存在 5 个仍需继续修复的问题**。这些问题并非编译级错误，而是会影响回答质量、召回率、状态语义、或前端能力溯源闭环的一致性问题。

### 8.5 已发现但未修复的问题（必须继续处理）

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

#### P1 — Skill 推荐与预算裁剪仍然耦合，可能导致“匹配到了却不下发推荐”

- **问题是什么**
  - 当前 `backend/routers/chat.py` 在注入 prompt 后把 `ctx` 替换为 `fitted_ctx`。
  - `_stream_with_metadata()` 又以这个裁剪后的 `ctx` 作为 `skill_suggestion` 发送依据。
  - `AssembledContext.fit_to_budget()` 中 `matched_skills` 排在 Know-how / 知识库之后，预算打满时 Skill 项可能被裁掉。

- **为什么重要**
  - Skill 推荐事件本身不占 LLM token。
  - 但现在它被错误地绑定到 prompt 预算结果，导致本来已经匹配到 Skill，前端却收不到推荐。

- **会影响什么**
  - 影响 Copilot 内联 Skill 闭环的一致性。
  - 用户会看到“模型回答里像是在暗示某个能力”，但 UI 没有对应推荐条。

- **涉及文件 / 函数**
  - `backend/services/context_assembler.py::AssembledContext.fit_to_budget`
  - `backend/routers/chat.py::_stream_with_metadata`
  - `backend/routers/chat.py::chat_completions`

- **建议怎么修**
  - 将“用于 prompt 注入的 Skill 上下文”和“用于前端推荐的 Skill 事件”解耦。
  - 预算裁剪只影响 prompt 注入；SSE 推荐事件应基于**原始匹配结果**或至少单独保留的 top skill。

- **优先级**：`P1`

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

#### P1 — `context_metadata` 只完成“后端注入 + 前端解析”，尚未完成落库 / 消费 / 展示闭环

- **问题是什么**
  - 后端已经发送 `context_metadata`，前端 `src/services/api.ts` 也已解析。
  - 但 `src/components/chat/ChatArea.tsx` 当前仍传入 `undefined` 作为 `onMetadata`。
  - `src/types/index.ts::Message` 还没有 metadata/source 相关字段。
  - `src/stores/chatStore.ts` 的消息写入与更新逻辑也没有 metadata 持久化能力。

- **为什么重要**
  - 这导致“能力溯源”只在协议层存在，在 UI 与状态层实际上没有闭环。
  - 用户无法稳定看到一条 assistant 消息到底引用了多少知识库、多少 Know-how、是否触发了 Skill 匹配。

- **会影响什么**
  - 影响前端设计目标“能力溯源可视化”的落地。
  - 后续刷新页面后也无法保留相关元数据。

- **涉及文件 / 函数**
  - `src/services/api.ts::streamChat`
  - `src/components/chat/ChatArea.tsx`
  - `src/types/index.ts::Message`
  - `src/stores/chatStore.ts::{addMessage, updateMessage}`
  - 后续展示大概率还需联动消息展示组件（如 `MessageBubble.tsx`）

- **建议怎么修**
  - 给 `Message` 增加 metadata/source 字段。
  - 在 `ChatArea` 中把 `onMetadata` 绑定到当前 assistant 消息。
  - 在 store 中支持对消息 metadata 的更新与持久化。
  - 在消息 UI 上展示最少可用版本的 source badge / summary。

- **优先级**：`P1`

### 8.6 下一步待办（必须继续执行）

1. **先修 P0：Know-how 相关性过滤**
   - 原因：这是当前最直接影响 LLM 回答质量的问题。
   - 目标：让 prompt 预算优先留给“与当前 query 真正相关”的规则与知识。

2. **再修短查询语义召回阈值**
   - 原因：这是第二个直接影响回答质量的问题，且改动小、收益明确。

3. **解耦 Skill 推荐与预算裁剪**
   - 原因：推荐事件本不消耗 token，不应因 prompt 预算满而被吞掉。

4. **完成 `context_metadata` 落库与展示闭环**
   - 原因：这是前端对“能力溯源”设计目标的最后一段断链。

5. **修复 Abort / Done 语义**
   - 原因：这是状态正确性问题，会影响自动命名与中止体验，但相对前两项对回答质量影响略低。

### 8.7 推荐处理顺序（含原因）

#### 第一优先序列：先保回答质量

1. `backend/services/context_assembler.py` — 修复 Know-how 全量注入
2. `backend/services/hybrid_search.py` — 将短查询阈值从 `< 4` 调整到 `< 2`

**原因**：这两项直接决定模型能否拿到“更准、更相关”的上下文，是当前最核心的质量瓶颈。

#### 第二优先序列：补协议与交互一致性

3. `backend/routers/chat.py` + `backend/services/context_assembler.py` — 解耦 Skill 推荐与预算
4. `src/types/index.ts` + `src/stores/chatStore.ts` + `src/components/chat/ChatArea.tsx`（必要时联动消息展示组件）— 补完 `context_metadata` 闭环

**原因**：这两项决定“后端已经做出的增强”能否稳定、完整、可视化地到达前端用户界面。

#### 第三优先序列：修正状态语义

5. `src/services/api.ts` + `src/components/chat/ChatArea.tsx` — 修复 Abort 误判为 Done

**原因**：这是重要一致性问题，但优先级略低于回答质量与能力下发完整性。

### 8.8 后续实现时必须遵守的背景约束

- **LLM 回答质量优先**，不能为了简化实现而牺牲回答质量。
- **Token 预算必须按完整条目注入**，禁止回退到拼接后硬截断。
- **SSE metadata 必须在 `[DONE]` 前注入**，前后端协议顺序不可破坏。
- **Skill 推荐必须保持 Copilot 对话内联闭环**，不要强行跳转 Agent 面板。
- **模式与对话状态必须按 `conversationId` 隔离**，避免串线。
- 中文 token 预算仍按保守估算：**1 个汉字 ≈ 0.6 token**。
- 当前构建与测试已通过，但这**不等于**逻辑审查完成；后续改动仍需继续执行构建与测试验证。

### 8.9 当前残余风险（即使暂未列为最高优先级，也不能遗忘）

- 当前未进行真正的前端 UI 自动化/E2E 验证；`context_metadata` 的最终展示链路仍未实装完成。
- `ChatArea.tsx` 当前 `prefillText` 是组件级单值状态，后续在补 metadata/推荐闭环时，需要顺手复查是否存在跨对话误写或覆盖未发送草稿的风险。
- 当前已通过构建与后端测试，但并未因此证明所有 SSE 边界时序都已覆盖；后续修复 `Abort` 语义后应补一次针对流中止场景的验证。

### 8.10 交接结论

- **已经完成**：Phase 1 主链路功能改造与基础验证。
- **已经确认没回退的点**：构建可过、后端测试可过、SSE 元数据顺序正确、Skill 推荐保持对话内联、token 预算不再硬截断。
- **仍必须继续修复**：Know-how 相关性过滤、短查询语义召回阈值、Skill 推荐预算耦合、Abort/Done 语义、`context_metadata` 闭环。
- **下次继续工作时，严格按 8.7 的顺序推进，不要重新做大范围排查。**
