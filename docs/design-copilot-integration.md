# Meeting Assistant — Copilot / Skill / Know-how / 知识库 协同集成设计文档

> 版本: v1.0 · 2026-03-18
> 状态: 设计阶段

---

## 目录

1. [问题定义：为什么"能力没打通"](#1-问题定义)
2. [目标场景与用户故事](#2-目标场景)
3. [架构总览：Orchestrator 层](#3-架构总览)
4. [意图识别与能力路由](#4-意图识别与能力路由)
5. [上下文组装与 Prompt 注入](#5-上下文组装与-prompt-注入)
6. [能力溯源 — "用了什么"可视化](#6-能力溯源)
7. [前端交互与状态流转](#7-前端交互与状态流转)
8. [后端 API 与数据流](#8-后端-api-与数据流)
9. [分阶段实施计划](#9-分阶段实施计划)
10. [风险与边界条件](#10-风险与边界条件)

---

## 1. 问题定义

### 1.1 现状：五大能力各自为政

| 模块 | 当前入口 | 当前实现 | 与其他模块的连接 |
|------|----------|----------|-----------------|
| **Copilot** | `ChatArea.tsx` → `chat.py` `/completions` | 纯 LLM 对话，system prompt 按 mode 注入 | ❌ 不查知识库、不看 Know-how、不触发 Skill |
| **Skill Builder** | `ChatArea.tsx` (builder mode) → 同一 `/completions` | 通过 builder system prompt 引导创建 Skill | ❌ 不参考已有 Skill 模板、不引用知识库 |
| **Agent** | `AgentExecutionPanel.tsx` → `agent_executor.py` | 关键词匹配 Skill → 逐步执行 | ❌ 执行时不查知识库、不应用 Know-how 规则 |
| **Know-how** | `KnowhowManager.tsx` → `knowhow_service.py` | CRUD 规则，`check_against_content` 关键词匹配 | ❌ 规则只在独立面板展示，从不注入对话 |
| **知识库** | `KnowledgeManager.tsx` → `knowledge_service.py` | 文件导入 + 向量检索 + 结构化查询 | ❌ 检索结果不进入 Copilot 对话上下文 |

### 1.2 割裂的四个层面

**① 用户视角**：用户必须"知道"自己要去哪个模块。想查数据要切到知识库面板，想检查规则要切到 Know-how 面板。自然语言无法跨模块。

**② 交互流程**：`ChatArea.tsx` 的 `handleSend` 函数对三种模式做了硬分支（`if currentMode === 'agent'`），每个分支独立处理，无统一编排。

**③ 状态流转**：`appStore.ts` 的 `currentMode` 控制全局视图切换，但模式之间没有数据传递机制。Copilot 模式下的对话无法触发 Agent 模式的 Skill 执行。

**④ 后端能力编排**：`chat.py` 的 `_build_messages()` 只注入静态 system prompt，没有动态上下文注入点。`agent_executor.py` 的 `_execute_step()` 只检查工具名是否出现在步骤描述中，不会主动去查知识库或 Know-how。

### 1.3 缺失的连接层

```
现状:  用户 → [模式切换] → 独立模块 → LLM / 工具
目标:  用户 → [自然语言] → Orchestrator → 并行调度各能力 → LLM 综合输出
```

缺失的正是中间的 **Orchestrator（编排层）**：一个能理解用户意图、决定调用哪些能力、组装上下文、返回综合结果的协调器。

---

## 2. 目标场景

### 场景 A：Copilot 对话自动增强

> 用户在 Copilot 中问："上次采购办公电脑的供应商是谁？价格合理吗？"

**期望行为**：
1. 识别为知识库查询 + Know-how 规则检查
2. 自动检索知识库中"办公电脑"相关采购记录
3. 自动应用 Know-how 中"价格偏差 ±15%"规则
4. LLM 综合生成回答，并标注："📚 引用了知识库 2 条记录 · 📋 应用了 1 条 Know-how 规则"

### 场景 B：Copilot 中自动触发 Skill

> 用户说："帮我做一下这份 PPT 的采购预审"

**期望行为**：
1. 识别为可执行任务 → 匹配到"采购预审"Skill
2. 在 Copilot 界面内显示推荐："🤖 找到匹配的 Skill「采购预审」，是否执行？"
3. 用户确认后，在当前对话中执行 Skill（不切换到 Agent 模式）
4. 执行过程中自动查知识库历史数据、应用 Know-how 规则

### 场景 C：Builder 中参考已有资源

> 用户在 Builder 中说："帮我创建一个供应商评估的 Skill"

**期望行为**：
1. 自动检索已有 Skill 列表，发现相关的"采购预审"Skill
2. 自动查 Know-how 中与"供应商评估"相关的规则
3. 生成的 Skill 模板自动引用这些规则作为检查步骤

### 场景 D：透明的能力溯源

> 任何模式下，回答中用到了知识库 / Know-how / Skill 的内容

**期望行为**：
- 消息气泡底部显示折叠的"能力引用"标签
- 点击展开可以看到具体引用了哪些知识片段、哪些规则、哪些 Skill 步骤

---

## 3. 架构总览

### 3.1 新增 Orchestrator 层

```
┌─────────────────────────────────────────────────────┐
│                    Frontend                          │
│  ChatArea.tsx ──→ POST /api/chat/completions         │
│                   (不再区分模式，统一入口)              │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Backend: Orchestrator                    │
│                                                      │
│  1. Intent Classifier (意图分类)                      │
│     ├─ CHAT: 普通对话                                 │
│     ├─ KNOWLEDGE_QUERY: 需要知识库检索                 │
│     ├─ SKILL_EXEC: 需要执行 Skill                     │
│     └─ COMPOSITE: 需要多种能力组合                     │
│                                                      │
│  2. Context Assembler (上下文组装)                     │
│     ├─ 知识库 RAG 片段                                │
│     ├─ Know-how 相关规则                              │
│     └─ Skill 匹配信息                                 │
│                                                      │
│  3. Prompt Composer (提示词编排)                       │
│     └─ system prompt + 动态上下文 + 用户消息            │
│                                                      │
│  4. Response Enricher (响应增强)                       │
│     └─ 附加能力溯源元数据                              │
└─────────────────────────────────────────────────────┘
```

### 3.2 与现有代码的映射

| 新组件 | 改造对象 | 改造方式 |
|--------|----------|----------|
| Intent Classifier | `chat.py` `_build_messages()` | 在消息构建前新增意图分类步骤 |
| Context Assembler | 新建 `backend/services/orchestrator.py` | 调用 `hybrid_search`, `knowhow_service`, `skill_matcher` |
| Prompt Composer | `chat.py` `_build_messages()` | 将静态 system prompt 扩展为动态组装 |
| Response Enricher | `chat.py` 流式响应 | 在 SSE `[DONE]` 之前追加元数据事件 |

### 3.3 核心设计原则

1. **渐进增强，不破坏现有链路**：所有新能力作为 `_build_messages()` 的增强注入，不改变现有 SSE 流式协议
2. **用户无需理解模块边界**：前端去掉硬模式切换，Orchestrator 自动判断需要什么能力
3. **延迟可控**：意图分类和上下文组装并行执行，总延迟不超过 500ms
4. **可回退**：如果 Orchestrator 判断不出意图，降级为纯 Copilot 对话

---

## 4. 意图识别与能力路由

### 4.1 意图分类设计

```python
# backend/services/orchestrator.py（核心伪代码）

class IntentType(Enum):
    CHAT = "chat"                    # 纯对话
    KNOWLEDGE_QUERY = "knowledge"    # 需要知识库检索
    KNOWHOW_CHECK = "knowhow"       # 需要规则校验
    SKILL_EXEC = "skill"            # 需要执行 Skill
    COMPOSITE = "composite"          # 组合意图

@dataclass
class Intent:
    primary: IntentType
    secondary: list[IntentType]      # 可能需要的辅助能力
    confidence: float
    extracted_entities: dict          # 提取的实体（品名、供应商名等）
```

### 4.2 两阶段分类策略

**为什么不直接用 LLM 分类？** 因为每次对话都额外调一次 LLM 会增加 1-3 秒延迟和额外费用。

**推荐方案：规则优先 + LLM 兜底**

```
Stage 1: 快速规则匹配（< 10ms）
  ├─ 关键词命中 Know-how 分类词 → KNOWHOW_CHECK
  ├─ 关键词命中 Skill keywords   → SKILL_EXEC
  ├─ 包含"查询/检索/历史/记录"等词 → KNOWLEDGE_QUERY
  ├─ 包含文件相关操作词           → SKILL_EXEC
  └─ 以上都未命中               → 进入 Stage 2

Stage 2: LLM 轻量分类（仅对 Stage 1 未命中的 ~30% 请求）
  ├─ 用一个极短 prompt（< 100 tokens）让 LLM 返回意图类型
  ├─ temperature = 0, max_tokens = 20
  └─ 超时 2s 则降级为 CHAT
```

### 4.3 实现：规则引擎

```python
# backend/services/intent_classifier.py

class IntentClassifier:
    """基于规则 + LLM 的两阶段意图分类器"""

    # Stage 1 关键词规则
    KNOWLEDGE_KEYWORDS = [
        "查询", "检索", "历史", "记录", "上次", "之前",
        "供应商", "价格", "采购", "对比", "统计",
    ]
    SKILL_KEYWORDS = [
        "执行", "运行", "预审", "分析", "生成报告",
        "帮我做", "自动化", "PPT",
    ]
    KNOWHOW_KEYWORDS = [
        "规则", "合规", "检查", "是否符合", "标准",
        "要求", "注意事项",
    ]

    def classify_fast(self, query: str, available_skills: list) -> Intent:
        """Stage 1: 规则快速分类"""
        query_lower = query.lower()
        intents = []

        # 检查各类关键词命中
        knowledge_hits = sum(1 for kw in self.KNOWLEDGE_KEYWORDS if kw in query_lower)
        skill_hits = sum(1 for kw in self.SKILL_KEYWORDS if kw in query_lower)
        knowhow_hits = sum(1 for kw in self.KNOWHOW_KEYWORDS if kw in query_lower)

        # Skill 匹配（复用现有 skill_matcher）
        skill_match = skill_matcher.match(query, available_skills)
        if skill_match and skill_match[0].score >= 0.6:
            intents.append(IntentType.SKILL_EXEC)

        if knowledge_hits >= 2:
            intents.append(IntentType.KNOWLEDGE_QUERY)
        if knowhow_hits >= 1:
            intents.append(IntentType.KNOWHOW_CHECK)

        if not intents:
            return Intent(primary=IntentType.CHAT, secondary=[], confidence=0.5)

        primary = intents[0]
        secondary = intents[1:] if len(intents) > 1 else []

        # 组合意图
        if len(intents) >= 2:
            primary = IntentType.COMPOSITE

        return Intent(
            primary=primary,
            secondary=secondary if primary != IntentType.COMPOSITE else intents,
            confidence=0.8,
            extracted_entities={},
        )
```

### 4.4 路由决策表

| 意图类型 | 调用的服务 | 上下文注入 | 响应增强 |
|---------|-----------|-----------|---------|
| `CHAT` | 仅 LLM | 基础 system prompt | 无 |
| `KNOWLEDGE_QUERY` | `hybrid_search.search()` → LLM | RAG 片段注入 prompt | 引用溯源 |
| `KNOWHOW_CHECK` | `knowhow_service.list_rules()` → LLM | 规则注入 prompt | 规则命中标记 |
| `SKILL_EXEC` | `skill_matcher.match()` → 确认 → `agent_executor` | Skill 信息注入 | Skill 推荐卡片 |
| `COMPOSITE` | 并行调用多个服务 → LLM 综合 | 多源上下文合并 | 多源溯源 |

---

## 5. 上下文组装与 Prompt 注入

### 5.1 动态上下文组装器

这是整套方案的核心。目标：将多源信息高效注入 LLM prompt，不超过 token 上限。

```python
# backend/services/context_assembler.py

class ContextAssembler:
    """动态上下文组装 — 将知识库/Know-how/Skill 信息注入 system prompt"""

    MAX_CONTEXT_CHARS = 4000  # 上下文注入上限（约 2000 tokens）

    async def assemble(self, intent: Intent, query: str) -> AssembledContext:
        """根据意图并行组装上下文"""
        tasks = []

        if IntentType.KNOWLEDGE_QUERY in self._all_intents(intent):
            tasks.append(self._fetch_knowledge(query))

        if IntentType.KNOWHOW_CHECK in self._all_intents(intent):
            tasks.append(self._fetch_knowhow(query))

        if IntentType.SKILL_EXEC in self._all_intents(intent):
            tasks.append(self._fetch_skills(query))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._merge_results(results)
```

### 5.2 Prompt 注入格式

改造后的 `_build_messages()` 生成的消息结构：

```
[system] 基础角色 prompt（来自 settings 或 _DEFAULT_PROMPTS）

         ── 以下为动态注入的上下文 ──

         📚 知识库参考：
         [1] 2024年12月采购记录 — 联想 ThinkPad T14s，供应商：京东企业购，
             单价 ¥8,500，总价 ¥170,000（来源：Q4采购总结.pptx 第3页）
         [2] ...

         📋 适用的 Know-how 规则：
         [1] 价格与历史同品类均价对比，偏差应在合理范围（±15%）内 [权重:3]
         [2] 是否有与该供应商的历史合作记录及合作评价 [权重:2]

         🔧 可用 Skill：
         [1] 采购预审 — 匹配度 0.85 — 可自动执行

         请基于以上参考信息回答用户问题。如果引用了知识库或 Know-how，
         请在回答末尾标注引用来源。

[user]   用户的实际问题
```

### 5.3 Token 预算分配

| 来源 | 最大 chars | 优先级 | 截断策略 |
|------|-----------|--------|---------|
| Know-how 规则 | 800 | 最高 | 按 weight 降序，截断低权重规则 |
| 知识库 RAG 片段 | 2000 | 高 | 按相似度降序，保留 top-3 |
| Skill 匹配信息 | 400 | 中 | 仅保留 top-1 的名称+描述 |
| 基础 system prompt | 800 | 基础 | 不截断 |

---

## 6. 能力溯源

### 6.1 元数据协议

在 SSE 流的 `[DONE]` 信号之前，插入一个特殊的元数据事件：

```json
data: {"type": "context_metadata", "sources": {
  "knowledge": [
    {"id": "rec_001", "content_preview": "联想 ThinkPad T14s...", "source_file": "Q4采购.pptx", "slide": 3, "relevance": 0.92}
  ],
  "knowhow": [
    {"rule_id": "kh_001", "rule_text": "价格偏差应在±15%内", "applied": true}
  ],
  "skills": [
    {"skill_id": "procurement-review", "skill_name": "采购预审", "match_score": 0.85, "suggested": true}
  ]
}}

data: [DONE]
```

### 6.2 前端展示

在 `MessageBubble.tsx` 中新增折叠式溯源标签：

```
┌─────────────────────────────────────────┐
│ 🤖 根据历史记录，上次采购办公电脑的供应  │
│ 商是京东企业购，单价 ¥8,500...           │
│                                         │
│ ┌─ 📎 引用来源 ──────────────────────┐   │
│ │ 📚 知识库: Q4采购.pptx 第3页       │   │
│ │ 📋 Know-how: 价格偏差±15% (已应用) │   │
│ └────────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

---

## 7. 前端交互与状态流转

### 7.1 模式简化

**现状**：用户必须手动在 Copilot / Builder / Agent 三模式间切换。

**改造方案**：保留模式概念但弱化切换要求：

| 改造项 | 改造前 | 改造后 |
|--------|--------|--------|
| 模式切换 | 必须切到 Agent 才能执行 Skill | Copilot 中自动推荐 Skill，用户点击确认即可执行 |
| 知识库/Know-how | 只能在独立面板查看 | 自动注入对话上下文，同时保留独立面板 |
| Agent 执行面板 | 独占整个聊天区 | 作为消息气泡内嵌组件展示 |

### 7.2 前端改造点

#### ChatArea.tsx 改造

```typescript
// 改造前：handleSend 中的硬分支
if (currentMode === 'agent') {
  // 独立的 Agent 逻辑
} else {
  // Copilot/Builder 逻辑
}

// 改造后：统一入口，由后端 Orchestrator 决定
const handleSend = async (content: string, attachmentContext?: string) => {
  let convId = activeConversationId || createConversation(currentMode);
  addMessage({ conversationId: convId, role: 'user', content });

  // 统一走 /api/chat/completions，后端自动编排
  // mode 仍然传递，作为 Orchestrator 的参考信号之一
  await streamChat(history, activeLLMConfig, onChunk, onDone, onError, signal, currentMode);
};
```

#### 新增：SkillSuggestionCard 组件

当 Orchestrator 检测到可执行 Skill 时，在消息流中插入推荐卡片：

```
┌──────────────────────────────────────────┐
│ 🤖 检测到可执行任务                        │
│                                          │
│ ┌── 采购预审 ────────────────────────┐    │
│ │ 📋 匹配度: 85%                     │    │
│ │ 📝 自动分析 PPT 并检查采购合规性     │    │
│ │                                    │    │
│ │  [▶ 执行]  [稍后再说]               │    │
│ └────────────────────────────────────┘    │
└──────────────────────────────────────────┘
```

#### 新增：SourceBadge 组件

```typescript
// src/components/chat/SourceBadge.tsx
interface SourceBadgeProps {
  sources: {
    knowledge: Array<{ source_file: string; slide?: number; relevance: number }>;
    knowhow: Array<{ rule_text: string; applied: boolean }>;
    skills: Array<{ skill_name: string; suggested: boolean }>;
  };
}
```

### 7.3 状态管理扩展

```typescript
// chatStore.ts 新增
interface MessageMetadata {
  sources?: {
    knowledge: KnowledgeSource[];
    knowhow: KnowhowSource[];
    skills: SkillSource[];
  };
  intent?: string;  // 识别到的意图类型
}

// Message 类型扩展
interface Message {
  // ...existing fields
  metadata?: MessageMetadata;  // 新增：能力溯源元数据
}
```

### 7.4 SSE 解析扩展

在 `api.ts` 的 `streamChat` 中，新增对 `context_metadata` 事件的处理：

```typescript
// api.ts streamChat 改造
const parsed = JSON.parse(data);

if (parsed.type === 'context_metadata') {
  // 不是文本内容，而是元数据事件
  onMetadata?.(parsed.sources);  // 新增回调
  continue;
}

if (parsed.type === 'skill_suggestion') {
  // Skill 推荐事件
  onSkillSuggestion?.(parsed.skill);
  continue;
}
```

---

## 8. 后端 API 与数据流

### 8.1 改造 `/api/chat/completions`

这是最关键的改造。不新增 API，而是增强现有接口：

```python
# backend/routers/chat.py — 改造后的 chat_completions

@router.post("/chat/completions")
async def chat_completions(request: ChatRequest):
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

    # ===== 新增：Orchestrator 编排 =====
    user_query = request.messages[-1].content if request.messages else ""

    # 1. 意图分类（< 10ms）
    intent = intent_classifier.classify_fast(
        user_query,
        available_skills=skill_manager.list_skills(),
    )

    # 2. 上下文组装（并行，< 200ms）
    assembled_context = await context_assembler.assemble(intent, user_query)

    # 3. 构建增强消息（注入动态上下文）
    messages = await _build_messages_enhanced(request, assembled_context)
    # ===== Orchestrator 编排结束 =====

    if request.stream:
        return StreamingResponse(
            _stream_with_metadata(messages, request, assembled_context),
            media_type="text/event-stream",
        )
    # ...
```

### 8.2 增强的消息构建

```python
async def _build_messages_enhanced(
    request: ChatRequest, context: AssembledContext
) -> list[dict]:
    """构建带动态上下文的消息列表"""
    messages = [m.model_dump() for m in request.messages]

    has_system = any(m["role"] == "system" for m in messages)
    if has_system:
        return messages

    # 基础 system prompt
    custom_prompt = await storage.get_setting(
        f"system_prompt_{request.mode}", default=""
    )
    base_prompt = (
        custom_prompt.strip()
        if custom_prompt.strip()
        else _DEFAULT_PROMPTS.get(request.mode, "")
    )

    # 动态上下文注入
    context_sections = []

    if context.knowledge_results:
        knowledge_text = "\n".join(
            f"[{i+1}] {r['content'][:200]}（来源：{r.get('source_file', '未知')}）"
            for i, r in enumerate(context.knowledge_results[:3])
        )
        context_sections.append(f"📚 知识库参考：\n{knowledge_text}")

    if context.knowhow_rules:
        rules_text = "\n".join(
            f"[{i+1}] {r['rule_text']} [权重:{r.get('weight', 2)}]"
            for i, r in enumerate(context.knowhow_rules[:5])
        )
        context_sections.append(f"📋 适用的 Know-how 规则：\n{rules_text}")

    if context.matched_skills:
        skill = context.matched_skills[0]
        context_sections.append(
            f"🔧 可用 Skill：{skill['skill_name']}（匹配度 {skill['score']:.0%}）"
        )

    # 组装最终 system prompt
    if context_sections:
        enhanced_prompt = (
            f"{base_prompt}\n\n"
            f"── 以下为系统自动检索到的相关信息 ──\n\n"
            f"{'\\n\\n'.join(context_sections)}\n\n"
            f"请基于以上参考信息回答用户问题。"
            f"如果引用了知识库或 Know-how，请在回答末尾标注引用来源。"
        )
    else:
        enhanced_prompt = base_prompt

    return [{"role": "system", "content": enhanced_prompt}] + messages
```

### 8.3 流式响应增强

```python
async def _stream_with_metadata(
    messages: list[dict],
    request: ChatRequest,
    context: AssembledContext,
) -> AsyncGenerator[str, None]:
    """带元数据的流式响应"""
    # 正常流式输出
    async for chunk in llm_service.stream_chat(
        messages=messages,
        model=request.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        api_url=request.api_url,
        api_key=request.api_key,
    ):
        if chunk.strip() == "data: [DONE]":
            # 在 [DONE] 之前插入元数据
            if context.has_sources:
                metadata = {
                    "type": "context_metadata",
                    "sources": context.to_source_dict(),
                }
                yield f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"
            yield chunk
            return
        yield chunk
```

### 8.4 新增文件清单

| 文件 | 职责 | 依赖 |
|------|------|------|
| `backend/services/intent_classifier.py` | 两阶段意图分类 | `skill_matcher`, `llm_service` |
| `backend/services/context_assembler.py` | 并行上下文组装 | `hybrid_search`, `knowhow_service`, `skill_matcher` |
| `backend/services/orchestrator.py` | 编排入口（组合上述两个） | `intent_classifier`, `context_assembler` |
| `src/components/chat/SourceBadge.tsx` | 能力溯源 UI 组件 | — |
| `src/components/chat/SkillSuggestionCard.tsx` | Skill 推荐卡片 | `api.agentExecute` |

### 8.5 改造文件清单

| 文件 | 改造内容 |
|------|---------|
| `backend/routers/chat.py` | `chat_completions` 接入 Orchestrator |
| `src/services/api.ts` | `streamChat` 新增 `onMetadata` 回调 |
| `src/components/chat/ChatArea.tsx` | 去掉 Agent 模式硬分支，接入元数据 |
| `src/components/chat/MessageBubble.tsx` | 新增 SourceBadge 渲染 |
| `src/stores/chatStore.ts` | Message 类型新增 metadata 字段 |
| `src/types/index.ts` | 新增 MessageMetadata 等类型定义 |

---

## 9. 分阶段实施计划

### P1（2 周）— 知识库 + Know-how 注入 Copilot

**目标**：用户在 Copilot 对话时，自动获得知识库和 Know-how 增强。

**MVP 交付物**：
- `intent_classifier.py` — Stage 1 规则分类（仅关键词）
- `context_assembler.py` — 知识库 RAG + Know-how 规则组装
- `chat.py` 改造 — `_build_messages_enhanced()`
- 前端无改动（P1 不展示溯源 UI，仅后端增强回答质量）

**验证标准**：
- 用户问"上次采购办公电脑的价格"，回答中包含知识库检索到的具体数据
- 用户问"这个采购方案合规吗"，回答中参考了 Know-how 规则

**技术风险**：
- 知识库为空时退化为纯对话（已处理）
- 上下文过长导致 token 超限 → 截断策略已设计

### P2（2 周）— 能力溯源 + Skill 推荐

**目标**：用户能看到回答引用了什么，并能在 Copilot 中触发 Skill。

**MVP 交付物**：
- SSE 元数据协议实现（`context_metadata` 事件）
- `SourceBadge.tsx` 溯源组件
- `SkillSuggestionCard.tsx` Skill 推荐卡片
- `api.ts` `streamChat` 元数据回调
- `chatStore.ts` Message metadata 扩展

**验证标准**：
- 每条引用了知识库/Know-how 的回答下方显示引用来源
- 当用户说"帮我做采购预审"，出现 Skill 推荐卡片，点击可执行

### P3（2 周）— Builder 增强 + LLM 意图分类

**目标**：Builder 模式自动参考已有资源；意图分类覆盖更多 case。

**MVP 交付物**：
- Builder system prompt 动态注入已有 Skill 列表和 Know-how 规则
- Stage 2 LLM 轻量分类（处理 Stage 1 未命中的情况）
- Skill 执行结果内嵌到 Copilot 消息流（替代独立 Agent 面板）

**验证标准**：
- Builder 中创建新 Skill 时，LLM 回答参考了已有 Skill 结构
- 模糊意图（如"帮我看看这个方案怎么样"）也能被正确分类

---

## 10. 风险与边界条件

### 10.1 性能风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 每次对话都查知识库 + Know-how | 增加 200-500ms 延迟 | 仅在意图分类命中时查询；设置 200ms 超时 |
| 上下文过长导致 token 超限 | LLM 截断或报错 | 严格 Token 预算分配（§5.3）|
| 并发请求下 SQLite 锁 | 查询超时 | 使用 `aiosqlite` WAL 模式（已采用）|

### 10.2 准确性风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 意图误分类（CHAT 误判为 SKILL_EXEC） | 用户看到不相关的 Skill 推荐 | Skill 推荐为"建议"而非自动执行；需用户确认 |
| 知识库检索到不相关内容 | LLM 回答受误导 | RAG 结果附带相似度分数，低于 0.5 不注入 |
| Know-how 规则过多导致 prompt 噪声 | LLM 回答质量下降 | 按 weight 降序截断，最多注入 5 条 |

### 10.3 边界条件

1. **知识库为空**：`context_assembler` 返回空列表，退化为纯对话，用户无感知
2. **Know-how 规则全部停用**：同上
3. **无可用 Skill**：不显示推荐卡片
4. **LLM 不遵循引用指令**：前端不依赖 LLM 回答中的引用格式，而是通过独立的 `context_metadata` 事件展示溯源
5. **Embedding 服务未配置**：知识库语义检索降级为 SQLite 关键词匹配（`hybrid_search` 已实现此回退）
6. **用户手动切到 Agent 模式**：保留现有 Agent 执行流程不变，Orchestrator 仅增强 Copilot 和 Builder

---

## 附录 A：关键数据流序列图

```
用户输入 "上次采购办公电脑的供应商是谁？"
    │
    ▼
ChatArea.tsx handleSend()
    │ POST /api/chat/completions {messages, mode: "copilot"}
    ▼
chat.py chat_completions()
    │
    ├─ intent_classifier.classify_fast()
    │   → KNOWLEDGE_QUERY (命中: "上次", "采购", "供应商")
    │
    ├─ context_assembler.assemble()
    │   ├─ hybrid_search.search("办公电脑 供应商")
    │   │   → [{item_name: "ThinkPad T14s", supplier: "京东企业购", ...}]
    │   └─ knowhow_service.list_rules(category="采购预审")
    │       → [{rule_text: "价格偏差±15%", weight: 3}, ...]
    │
    ├─ _build_messages_enhanced()
    │   → system prompt + RAG片段 + Know-how规则 + 用户消息
    │
    ├─ llm_service.stream_chat()
    │   → SSE: data: {"choices":[{"delta":{"content":"根据..."}}]}
    │   → SSE: data: {"type":"context_metadata","sources":{...}}
    │   → SSE: data: [DONE]
    │
    ▼
前端 streamChat() onChunk / onMetadata / onDone
    │
    ├─ MessageBubble 渲染回答内容
    └─ SourceBadge 渲染引用来源
```

---

## 附录 B：设计决策记录

| 决策 | 选项 A | 选项 B | 选择 | 理由 |
|------|--------|--------|------|------|
| 意图分类方式 | 纯 LLM 分类 | 规则优先 + LLM 兜底 | **B** | 避免每次请求额外 LLM 调用的延迟和费用 |
| 上下文注入方式 | 独立 API 预处理 | 嵌入 system prompt | **system prompt** | 不改变 SSE 协议；LLM 天然能理解 system 指令 |
| Skill 触发方式 | 自动执行 | 推荐卡片 + 用户确认 | **推荐确认** | 避免误触发高风险操作 |
| 溯源展示方式 | LLM 回答中内嵌引用 | 独立元数据事件 | **独立事件** | LLM 引用格式不可控；独立事件确保 UI 一致性 |
| 前端模式改造 | 完全去掉模式 | 保留模式但弱化 | **弱化** | 渐进改造，不破坏已有 Builder/Agent 专用 UI |
