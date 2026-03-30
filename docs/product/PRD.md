# Meeting Assistant 产品需求文档（PRD）

> 版本：v2.1  
> 日期：2026-03-30  
> 状态：当前基线 / 施工中

---

## 1. 文档目的

本文档用于覆盖旧版 PRD，作为当前项目的唯一产品基线。

本次重写的核心目标是：

- 明确区分 `chat` 与 `agent` 两条运行链路
- 明确区分“全局资源”“角色策略”“运行时工具”“上下文展示”四个层级
- 为后续重构提供一致的前端展示规则与后端处理原则
- 在不破坏当前系统稳定性的前提下，定义分阶段落地路径

如果旧文档与本文档冲突，以本文档为准。

---

## 2. 当前产品定位

Meeting Assistant 是一个以对话与任务执行为核心的 AI 工作台，当前主要围绕以下能力展开：

- 使用 `chat` surface 做问答、总结、分析、讨论
- 使用 `agent` surface 做任务执行、步骤推进、结构化产出
- 使用知识库、Skill、Know-how、导入文件等资源增强回答与执行
- 通过“角色”控制不同场景下的授权与行为边界

当前产品不是“三模式硬切换工具”，而是：

- 两条 surface：`chat` / `agent`
- 一套动态角色系统：Role Policy
- 一组全局资源：Knowledge / Skill / Know-how / Imports
- 一套上下文与执行结果回写机制

---

## 3. 核心设计原则

### 3.1 四层分离

系统必须严格区分以下四层：

1. 全局资源层
2. 角色策略层
3. 运行时层
4. 展示层

任何一个开关、按钮、面板、接口，都必须能明确归属其中一层。

### 3.2 Chat 与 Agent 明确分工

`chat` 用于“对话增强”，`agent` 用于“任务执行”。

二者共享模型、资源和角色体系，但不共享同一套运行语义。

### 3.3 资源与权限分离

资源是否存在，不等于当前角色是否允许使用。

例如：

- Skill 列表中存在某个 Skill，不等于当前角色会自动推荐它
- 知识库中已有导入文件，不等于当前角色可以在 Agent 运行时读取它

### 3.4 当前上下文与资源库分离

“这次回答实际用了什么”与“系统里有哪些资源”必须分开展示，不能混在同一个认知容器中。

---

## 4. 目标心智模型

### 4.1 全局资源层

全局资源是系统资产，由系统统一管理，不由角色创建或定义。

当前资源类型：

- 知识库 Knowledge Base
- Skill 库 Skill Library
- Know-how 规则库
- 已导入文件 Imports

它们的职责是：

- 被检索
- 被引用
- 被 Agent 工具读取
- 在资源面板或管理入口中展示

### 4.2 角色策略层

角色只负责回答这几个问题：

- 这个角色是否可用于 `chat`
- 这个角色是否可用于 `agent`
- 在 `chat` 中允许哪些自动增强能力
- 在 `agent` 中执行前允许哪些预处理能力
- 在 `agent` 中运行时允许调用哪些工具

角色不负责决定资源是否存在，也不负责资源管理。

### 4.3 运行时层

系统存在两条独立运行链路：

#### Chat Surface

定位：

- 问答
- 讨论
- 总结
- 分析

运行方式：

- 用户输入问题
- 系统按角色策略决定是否做自动增强
- 系统将检索结果注入 prompt
- 模型输出回答
- 系统写入上下文元数据与可选 Skill 建议

#### Agent Surface

定位：

- 执行任务
- 跑步骤
- 调工具
- 产出结构化结果

运行方式：

- 用户输入任务
- 系统按角色策略决定是否预匹配 Skill
- 系统按角色策略决定是否先做执行前检索
- Agent 启动执行
- Agent 按工具权限调用运行时工具
- 结果回写到会话消息

### 4.4 展示层

展示层必须分成两类内容：

#### 当前上下文

显示最近一次回答或最近一次 Agent 执行实际使用到的内容，例如：

- 引用来源
- 检索计划
- Skill 建议
- Agent 结果摘要

#### 资源库

显示系统内当前已有的资源，例如：

- Skill 库
- 知识库资源
- Know-how 规则库

资源库展示不应暗示当前角色一定启用了对应能力。

---

## 5. 统一术语

为减少歧义，前后端产品文案统一采用以下术语。

### 5.1 Chat 相关术语

- `自动知识检索`
含义：Chat 允许系统自动从知识库检索上下文

- `自动规则检索`
含义：Chat 允许系统自动从 Know-how 规则库检索上下文

- `自动 Skill 建议`
含义：Chat 允许系统自动推荐适合的 Skill，但不会直接启动 Agent 执行

### 5.2 Agent 相关术语

- `预匹配 Skill`
含义：Agent 启动前，系统可以先尝试把当前任务匹配到某个 Skill

- `执行前自动知识检索`
含义：Agent 启动前，系统可以先从知识库补充执行上下文

- `执行前自动规则检索`
含义：Agent 启动前，系统可以先从 Know-how 规则库补充执行上下文

- `读取 Skill 定义`
含义：Agent 运行时可以读取某个 Skill 的定义内容

- `读取导入文件`
含义：Agent 运行时可以读取已导入文件的文本内容

- `主动查询知识库`
含义：Agent 运行时可以主动调用工具查询知识库

- `主动查询规则库`
含义：Agent 运行时可以主动调用工具查询 Know-how 规则库

### 5.3 禁止继续作为主文案使用的旧术语

以下命名可保留为技术兼容字段，但不再作为用户主文案：

- `RAG 知识检索`
- `技能匹配`
- `Skill 定义`
- `文件提取`
- `知识库查询`

原因：

- 它们混合了技术实现与产品语义
- 在 chat 与 agent 中指代层级不一致
- 容易让用户误以为是同一类开关

---

## 6. 当前产品结构

### 6.1 全局资源

#### 知识库

作用：

- 供 Chat 自动检索
- 供 Agent 执行前补充上下文
- 供 Agent 运行时主动查询

#### Skill 库

作用：

- 供 Chat 产生 Skill 建议
- 供 Agent 做任务预匹配
- 供 Agent 运行时读取 Skill 定义

#### Know-how 规则库

作用：

- 供 Chat 自动补充规则性上下文
- 供 Agent 执行前补充上下文
- 供 Agent 运行时主动查询规则

#### 已导入文件

作用：

- 作为知识库导入来源
- 作为 Agent 工具可读取的原始内容来源

### 6.2 角色模型

角色当前至少包含以下策略信息：

- `allowed_surfaces`
- `system_prompt`
- `agent_prompt`
- `capabilities`
- `agent_allowed_tools`

在当前代码兼容阶段，旧字段继续有效；后续将演进为更清晰的策略结构。

### 6.3 Surface

#### Chat Surface

用户通过普通对话输入请求，系统根据角色能力自动增强回答。

#### Agent Surface

用户通过任务型输入触发 Agent 执行，系统在运行前和运行中按权限做编排与工具调用。

---

## 7. 目标角色策略模型

### 7.1 产品层模型

目标角色模型如下：

```text
Role
├─ allowed_surfaces
├─ prompts
│  ├─ system_prompt
│  └─ agent_prompt
├─ chat_capabilities
│  ├─ auto_knowledge
│  ├─ auto_knowhow
│  └─ auto_skill_suggestion
├─ agent_preflight
│  ├─ pre_match_skill
│  ├─ auto_knowledge
│  └─ auto_knowhow
└─ agent_allowed_tools
   ├─ get_skill_definition
   ├─ extract_file_text
   ├─ query_knowledge
   └─ search_knowhow_rules
```

### 7.2 兼容策略

短期内保持以下兼容原则：

- 保留旧字段读取能力
- 前端文案先更新，后端字段分阶段迁移
- 在迁移完成前，旧字段与新文案之间允许存在映射层

### 7.3 关键解释

- `chat_capabilities` 是自动增强权限，不是运行时工具
- `agent_preflight` 是执行前编排，不是运行时工具
- `agent_allowed_tools` 才是 Agent 运行中真正可调用的工具

---

## 8. 运行时触发矩阵

### 8.1 Chat Surface

```text
用户消息
-> 读取当前角色
-> 检查 chat_capabilities
-> 自动检索知识 / 规则 / Skill 建议
-> 注入 prompt
-> LLM 回答
-> 输出 context metadata / skill suggestion
```

规则：

- Chat 不调用 Agent 运行时工具
- Chat 可以产生 Skill 建议
- Chat 不负责步骤执行

### 8.2 Agent Surface

```text
用户任务
-> 读取当前角色
-> 校验 agent surface 是否允许
-> 检查 agent_preflight
-> 可选：预匹配 Skill
-> 可选：执行前检索
-> 启动 Agent
-> 注册运行时工具
-> 执行并回写结果
```

规则：

- Agent 可以在零工具情况下运行
- 零工具表示“无工具执行”，不表示“Agent 被禁用”
- 预匹配与执行前检索不等于工具调用

---

## 9. 前端信息架构目标

### 9.1 角色设置页

角色设置页应按 surface 与行为类型分组，而不是把所有能力并列堆放。

目标结构：

```text
角色设置
├─ 基础信息
│  ├─ 名称
│  ├─ 图标
│  ├─ 描述
│  └─ 通用 Prompt
├─ Chat 模式
│  ├─ 可用于 Chat
│  ├─ 自动知识检索
│  ├─ 自动规则检索
│  └─ 自动 Skill 建议
└─ Agent 模式
   ├─ 可用于 Agent
   ├─ Agent 专用 Prompt
   ├─ 执行前能力
   │  ├─ 预匹配 Skill
   │  ├─ 执行前自动知识检索
   │  └─ 执行前自动规则检索
   └─ 运行时工具
      ├─ 读取 Skill 定义
      ├─ 读取导入文件
      ├─ 主动查询知识库
      └─ 主动查询规则库
```

### 9.2 右侧面板

右侧面板应拆为两个认知区块：

```text
上下文与资源
├─ 当前上下文
│  ├─ 最近回答引用
│  ├─ 最近检索计划
│  ├─ 最近 Skill 建议
│  └─ 最近 Agent 结果
└─ 资源库
   ├─ Skill 库
   ├─ 知识库资源
   └─ Know-how 规则库
```

展示规则：

- “当前上下文”仅展示最近一次回答或执行实际使用到的内容
- “资源库”仅展示系统现有资源，不暗示当前角色已启用

### 9.3 文案原则

- 不再将“能力”“工具”“资源”作为同义词混用
- 不再让一个标签同时表示 chat 自动增强与 agent 工具权限
- 所有说明文案必须明确“谁触发、何时触发、影响哪个 surface”

---

## 10. 后端处理原则

### 10.1 Chat Router

职责：

- 只读取 chat 相关能力
- 决定是否自动组装知识、规则、Skill 建议
- 输出与最近回答相关的上下文元数据

不应依赖：

- Agent 运行时工具权限

### 10.2 Agent Router / Runtime

职责：

- 校验 Agent surface 权限
- 根据 preflight 配置决定是否预匹配 Skill
- 根据 preflight 配置决定是否执行前检索
- 严格按 `agent_allowed_tools` 注册运行时工具

### 10.3 Context 数据

职责：

- 当前回答上下文数据来源于 message metadata / run metadata
- 资源库数据来源于管理接口
- 前端渲染时必须避免把二者混为一谈

---

## 11. 当前问题清单

以下是当前系统中已确认的主要认知冲突：

### 11.1 设置页中的同层混排

当前“RAG 知识检索”“技能匹配”“Agent 可用工具”同时出现，但它们实际属于不同层级：

- Chat 自动增强
- Agent 执行前行为
- Agent 运行时工具

### 11.2 右侧面板语义混杂

当前“上下文”面板同时包含：

- 最近回答引用
- 全局 Skill 列表
- 知识库统计
- Know-how 概览

用户容易误以为这些都是“本次回答实际用到的上下文”。

### 11.3 Agent 全关工具仍可运行

这是当前设计允许的行为，但 UI 没有充分解释，导致用户误以为开关失效。

### 11.4 Skill 相关语义重叠

目前“技能匹配”“Skill 定义”“右侧可用 Skill”并非同一逻辑层，却使用了非常接近的命名。

---

## 12. 分阶段施工方案

### 12.1 Phase 1：文案与信息架构整理

风险：低

目标：

- 重写 PRD
- 补充改造蓝图
- 调整设置页分组与文案
- 调整右侧面板分区与说明

原则：

- 不修改核心运行语义
- 不改数据库结构
- 不影响现有功能可用性

### 12.2 Phase 2：策略语义清理

风险：中

目标：

- 引入明确的 `chat_capabilities`
- 引入明确的 `agent_preflight`
- 让 `/agent/match` 受预匹配开关控制
- 让 Chat 自动增强只受 Chat 能力控制

原则：

- 保持旧字段兼容
- 在迁移期间允许前后端做字段映射

### 12.3 Phase 3：命名与兼容收尾

风险：低

目标：

- 清理历史歧义文案
- 逐步淡化旧术语
- 补齐用户教育与说明文案

---

## 13. 验收标准

本轮重构成功的标准如下：

1. 用户能明确区分 Chat 自动增强与 Agent 工具调用
2. 用户能理解“资源存在”与“角色已授权”是两回事
3. 右侧面板能明显区分“当前上下文”与“资源库”
4. 关闭某个 Agent 工具时，用户不会再误以为 Agent 被禁用
5. 前端文案与后端运行语义使用同一套术语

---

## 14. 本轮施工范围

本轮立即启动的范围是：

- 文档基线重建
- 设置页信息架构整理
- 右侧面板信息架构整理

本轮不直接包含：

- 大规模后端字段迁移
- 高风险运行时语义改写
- 数据库结构破坏式调整

---

## 15. 与实现的关系

本文档定义的是“当前基线 + 目标方向”。

其中：

- Phase 1 内容应立即体现在前端展示和说明文案中
- Phase 2、Phase 3 内容作为后续连续施工计划推进

为了避免系统不稳定，本项目后续施工遵循以下原则：

- 先统一文档与认知
- 再做低风险界面整理
- 再做后端语义收口
- 每一步都要通过构建与测试验证

---

## 16. 关联文档

- 改造蓝图：[docs/development/CHAT_AGENT_REFACTOR_BLUEPRINT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/CHAT_AGENT_REFACTOR_BLUEPRINT.md)
- 当前状态说明：[docs/CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- SSE 元数据说明：[docs/reference/SSE_CONTEXT_METADATA.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/reference/SSE_CONTEXT_METADATA.md)

---

## 17. 多租户与权限管理（RBAC）

> 本章记录 v2.1 新增的多租户用户管理与基于角色的访问控制系统，为后续 Domain Management 集成打下基础。

### 17.1 核心概念区分

**极其重要**：本系统存在两套“角色”概念，务必严格区分：

| 概念 | 英文 | 定义 | 存储位置 |
|------|------|------|------|
| 系统用户角色 | System Role | 控制登录账户的管理权限（`admin` / `user`） | `users.system_role` 字段 |
| AI 角色 / 角色人格 | AI Role / Persona | 控制 Chat 与 Agent 行为的配置（如 Copilot、采购专家） | `roles` 表 |

**两者完全独立，不可混淡**：

- 系统用户 `admin` 登录后看到的是“用户管理”入口，与 AI 角色列表无关。
- AI 角色（Copilot / 执行助手等）是对话能力配置，所有登录用户均可使用，不受系统角色限制。

### 17.2 系统用户模型

系统用户（System User）是拥有登录凭据的人员账户：

```text
User
├─ id            UUID
├─ username      登录名（唯一）
├─ display_name  显示名称
├─ password_hash bcrypt 哈希后的密码
├─ system_role   "admin" | "user"
├─ group_id      所属用户组（可为空）
├─ is_active     账户是否启用
└─ created_at / updated_at
```

系统角色权限：

- `admin`：可访问用户管理 API（创建/删除用户、管理用户组、设置资源授权），可调用全部受保护端点。
- `user`：只能访问自身数据及有权限的资源，不能访问 `/api/auth/users`、`/api/auth/groups`、`/api/auth/grants` 等管理端点。

### 17.3 用户组模型

```text
Group
├─ id          UUID
├─ name        组名（唯一）
├─ description 描述
└─ created_at
```

用户通过 `users.group_id` 归属到某一个用户组，一个用户只能属于一个组。

### 17.4 资源授权（Access Grants）模型

```text
AccessGrant
├─ id            UUID
├─ resource_type "knowledge" | "role" | "skill"
├─ resource_id   目标资源的 UUID
├─ grant_type    "public" | "group" | "user"
├─ grantee_id    当 grant_type 为 "group" 或 "user" 时，填入对应 ID
└─ created_at
```

### 17.5 资源可见性规则

每条资源（Knowledge / AI Role / Skill）遵循以下可见性逻辑：

| 可见性 | 描述 | 判断条件 |
|--------|------|----------|
| **Private（私有）** | 仅创建者可见 | 无 Access Grant 且 `owner_id = 当前用户 id` |
| **Group（组内共享）** | 同组用户可见 | 存在 `grant_type="group"` 且 `grantee_id = 当前用户的 group_id` |
| **Public（公开）** | 所有登录用户可见 | 存在 `grant_type="public"` 或资源为内置（`is_builtin=1`） |

补充规则：

- **管理员绕过过滤**：`system_role="admin"` 的用户在后端跳过 `owner_id` 过滤，可看到全部资源。
- **内置资源始终可见**：`is_builtin=1` 的资源对所有用户可见，不受 Access Grants 约束。

### 17.6 认证流程

```text
用户输入用户名+密码
→ POST /api/auth/login
→ 后端验证 bcrypt hash
→ 签发 JWT（payload: sub=user_id, username, role, exp）
→ 前端 authStore 持久化 token
→ 后续所有请求通过 authFetch 注入 Authorization: Bearer <token>
→ 后端 get_current_user 依赖解码 token 并注入用户上下文
```

JWT 有效期默认 **24 小时**（可通过环境变量 `JWT_EXPIRE_MINUTES` 调整）。

### 17.7 默认账户

首次启动时，如果数据库中不存在任何 `system_role="admin"` 的用户，系统自动创建默认管理员：

- **用户名**：`admin`
- **密码**：`admin123`

> ⚠️ **生产环境必须在首次登录后立即修改默认密码。**

### 17.8 待完善事项

- [ ] Knowledge / AI Role / Skill 创建/编辑 UI 中增加可见性选择器（Private / Group / Public）
- [ ] 资源列表页根据当前用户的 Access Grants 过滤显示内容
- [ ] 支持将用户从一个组迁移到另一个组
