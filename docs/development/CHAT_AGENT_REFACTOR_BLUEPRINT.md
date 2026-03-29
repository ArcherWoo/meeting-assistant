# Chat / Agent / Context Refactor Blueprint

## Status

- Version: v1
- Date: 2026-03-29
- Scope: product and architecture baseline for the chat / agent / context cleanup

## Problem Statement

The current project mixes four different concepts in the same UI and mental model:

1. Global resources
2. Role permissions
3. Runtime orchestration
4. Context / resource display

This causes three recurring problems:

- The same word means different things on different surfaces, especially around "Skill", "RAG", and "tool".
- Users cannot tell whether a switch controls chat auto-enhancement, agent preflight behavior, or runtime tool calls.
- The right context panel mixes "what this answer used" with "what exists in the system".

This blueprint separates those responsibilities and defines a migration path that keeps the product stable while the model is cleaned up.

## Target Mental Model

### 1. Global Resource Layer

Global resources are system assets. They are not role permissions.

- Knowledge Base
- Skill Library
- Know-how Rule Library
- Imported Files

These are managed centrally and can be displayed in a resource panel or management area.

### 2. Role Policy Layer

Roles only answer authorization and orchestration questions.

- Can this role be used on `chat`?
- Can this role be used on `agent`?
- On `chat`, what can be auto-used?
- On `agent`, what can run before execution?
- On `agent`, which tools may be called during execution?

### 3. Runtime Layer

`chat` and `agent` are two different execution paths.

#### Chat Surface

Purpose:

- ask
- discuss
- summarize
- analyze

Behavior:

- user sends a prompt
- system may auto-retrieve evidence
- model replies
- system may emit context metadata and skill suggestions

#### Agent Surface

Purpose:

- execute a task
- follow steps
- use tools
- return structured outputs

Behavior:

- user submits a task
- system may pre-match a skill
- system may pre-retrieve execution context
- agent runs
- agent may call runtime tools
- final result is written back to the conversation

### 4. Display Layer

The UI must separate:

- Current Context: what the latest answer or run actually used
- Resource Library: what assets exist globally in the system

## Terminology Standard

The following names should become canonical in both frontend and backend-facing product copy.

### Chat Terms

- `自动知识检索`
  Meaning: chat may automatically retrieve from the knowledge base

- `自动规则检索`
  Meaning: chat may automatically retrieve from know-how rules

- `自动 Skill 建议`
  Meaning: chat may automatically recommend a skill, but does not start agent execution

### Agent Terms

- `预匹配 Skill`
  Meaning: before agent execution, the system may try to map the task to a skill

- `执行前自动知识检索`
  Meaning: before agent execution, the system may assemble knowledge context

- `执行前自动规则检索`
  Meaning: before agent execution, the system may assemble know-how context

- `读取 Skill 定义`
  Meaning: runtime tool allowing the agent to read a skill definition

- `读取导入文件`
  Meaning: runtime tool allowing the agent to read imported file text

- `主动查询知识库`
  Meaning: runtime tool allowing the agent to query the knowledge base while running

- `主动查询规则库`
  Meaning: runtime tool allowing the agent to query the rule library while running

## Target Policy Model

### Product-Level Role Model

```text
Role
├─ allowed_surfaces
├─ chat_capabilities
│  ├─ auto_knowledge
│  ├─ auto_knowhow
│  └─ auto_skill_suggestion
├─ agent_preflight
│  ├─ pre_match_skill
│  ├─ auto_knowledge
│  └─ auto_knowhow
├─ agent_allowed_tools
│  ├─ get_skill_definition
│  ├─ extract_file_text
│  ├─ query_knowledge
│  └─ search_knowhow_rules
└─ prompts
   ├─ system_prompt
   └─ agent_prompt
```

### Compatibility Strategy

Current database fields should remain valid during migration:

- `capabilities`
- `allowed_surfaces`
- `agent_allowed_tools`
- `agent_prompt`

Target evolution:

- keep old fields readable
- add new fields behind migration
- map old fields into the new model during transition

## Runtime Trigger Matrix

### Chat Surface

```text
User message
-> load current role
-> read chat_capabilities
-> auto retrieval (knowledge / knowhow / skill suggestion)
-> inject context into prompt
-> LLM response
-> emit context metadata / skill suggestion
```

Rules:

- chat never calls runtime agent tools
- chat may emit skill suggestions
- chat does not execute tasks

### Agent Surface

```text
User task
-> load current role
-> verify agent surface allowed
-> read agent_preflight
-> optional skill pre-match
-> optional preflight retrieval
-> run agent
-> register runtime tools from agent_allowed_tools
-> write back final result
```

Rules:

- agent may run with zero tools
- zero tools means "tool-less execution", not "agent disabled"
- preflight controls are not the same as runtime tools

## Frontend IA Target

### Settings Modal

Role settings should be grouped by surface and behavior type.

```text
Role Settings
├─ Basic Info
│  ├─ name
│  ├─ icon
│  ├─ description
│  └─ shared system prompt
├─ Chat Mode
│  ├─ enabled on chat
│  ├─ auto knowledge retrieval
│  ├─ auto knowhow retrieval
│  └─ auto skill suggestion
└─ Agent Mode
   ├─ enabled on agent
   ├─ agent prompt
   ├─ preflight behavior
   │  ├─ pre-match skill
   │  ├─ preflight knowledge retrieval
   │  └─ preflight knowhow retrieval
   └─ runtime tools
      ├─ read skill definition
      ├─ read imported files
      ├─ query knowledge
      └─ query knowhow
```

### Right Panel

The current right panel should be split conceptually into two areas.

```text
Context & Resources
├─ Current Context
│  ├─ latest answer references
│  ├─ latest retrieval plan
│  ├─ latest skill suggestion
│  └─ latest agent result
└─ Resource Library
   ├─ skill library
   ├─ knowledge base
   └─ knowhow library
```

Design rule:

- "Current Context" means what was actually used in the latest reply or run
- "Resource Library" means what exists globally

## Backend Responsibility Split

### Chat Router

File:

- `backend/routers/chat.py`

Target responsibility:

- read chat-only capabilities
- decide which surfaces are auto-retrieved on chat
- emit metadata for the latest answer

It should not depend on runtime agent tool permissions.

### Agent Router and Runtime

Files:

- `backend/routers/agent.py`
- `backend/services/agent_runtime/runner.py`
- `backend/services/agent_runtime/role_policy.py`

Target responsibility:

- validate role access to agent surface
- control skill pre-match with agent preflight config
- control execution-time retrieval with agent preflight config
- register runtime tools strictly from `agent_allowed_tools`

### Context Panel Data

Files:

- `src/components/layout/ContextPanel.tsx`

Target responsibility:

- render current answer metadata from message metadata
- render resource library from management APIs
- never imply that a listed resource is necessarily enabled for the current role

## Phased Construction Plan

### Phase 1: Copy and IA Cleanup

Risk: low

Goals:

- rename labels
- split settings copy into chat mode vs agent mode
- split right panel into current context vs resource library
- keep backend behavior unchanged

### Phase 2: Policy Semantics Cleanup

Risk: medium

Goals:

- add explicit `chat_capabilities`
- add explicit `agent_preflight`
- make `/agent/match` respect agent preflight switch
- make chat retrieval respect chat-only switches

### Phase 3: Naming and Compatibility Cleanup

Risk: low

Goals:

- reduce overloaded terminology
- preserve backward compatibility during migration
- remove misleading UI copy

## Acceptance Criteria

The refactor is successful when:

1. A user can explain the difference between chat auto-enhancement and agent runtime tools without reading code.
2. The right panel clearly separates current answer context from global resources.
3. Turning off an agent tool never implies that agent itself is disabled.
4. Turning off a chat capability only affects chat auto-enhancement, not unrelated agent runtime behavior.
5. Product copy and backend logic use the same vocabulary.

## Immediate Construction Scope

This round starts with Phase 1 only:

- documentation baseline
- settings modal structure and copy cleanup
- context panel information architecture cleanup

No high-risk runtime logic changes are required for Phase 1.
