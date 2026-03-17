# Meeting Assistant — 开发总结文档

## 1. 项目概述

**Meeting Assistant** 是一款面向专业用户的 AI 会议助手桌面应用（macOS / Windows），核心功能包括：

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
| Electron | 最新 | 跨平台桌面壳 |
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
- Electron 应用壳搭建（主进程 + preload + 渲染进程）
- FastAPI 后端基础框架，动态端口分配（`PythonManager`）
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
├── electron/
│   ├── main.ts            # Electron 主进程；启动 PythonManager、注册 IPC
│   ├── preload.ts         # 安全暴露 electronAPI 给渲染进程
│   └── python-manager.ts  # 动态端口分配、后端进程生命周期管理
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
│   ├── main.tsx           # React 入口；初始化后端端口（initBackend）
│   ├── services/api.ts    # 所有 HTTP/SSE 调用封装；getBaseUrl() 动态端口
│   ├── stores/
│   │   ├── chatStore.ts   # 多会话状态 + localStorage 持久化
│   │   └── appStore.ts    # 全局应用状态（后端连接状态等）
│   └── components/
│       ├── chat/
│       │   ├── ChatArea.tsx   # 消息列表、handleSend、流式渲染
│       │   └── ChatInput.tsx  # 输入框、📎 附件模式、文本提取
│       └── layout/
│           └── ContextPanel.tsx  # 右侧面板：知识库统计、导入、删除
└── start.py               # 一键启动脚本（环境检测 + 并行启动前后端）
```

---

## 5. 已知问题与限制

| 问题 | 说明 |
|------|------|
| LanceDB 未安装 | 向量检索（RAG）不可用；知识库只存元数据，无法语义检索 |
| Electron 动态端口 | 每次启动端口随机；`start.py` 启动的后端（8765）与 Electron 内置后端不同，两者独立 |
| PDF/Word/Excel 解析 | 依赖 PyMuPDF / python-docx / openpyxl，未安装则相应格式无法解析 |
| Windows 兼容性 | `start.py` 主要在 macOS/Linux 测试；Windows 下颜色码可能失效 |
| 知识库向量搜索 | 当前 RAG 管道尚未完整接入对话（检索结果未自动注入 prompt） |

---

## 6. 本地开发指南

### 快速启动（推荐）

```bash
python3 start.py
```

脚本会自动检测环境、安装缺失依赖，并并行启动前后端。

### 手动分别启动

**后端**（开发模式，支持热重载）：
```bash
cd backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

**前端**（Vite + Electron）：
```bash
npm run dev
```

### 端口说明

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端（手动启动） | 8765 | 固定端口，`start.py` 使用 |
| 后端（Electron 内置） | 随机 | Electron 自动分配，通过 IPC 传给前端 |
| 前端 Vite | 5173 | 浏览器访问地址 |

> ⚠️ 通过 `npm run dev` 启动 Electron 时，Electron 会自己在随机端口启动后端，与 `start.py` 的后端互相独立。

### 数据存储路径

```
~/.meeting-assistant/
├── knowledge.db    # SQLite 元数据
└── vectors/        # LanceDB 向量数据
```

---

## 7. GitHub 上传前注意事项

确认 `.gitignore` 包含以下内容：

```gitignore
# 构建产物
dist/
dist-electron/

# 依赖
node_modules/

# Python 缓存
__pycache__/
*.pyc
*.pyo
backend/__pycache__/

# 环境配置（含 API Key）
.env
.env.local
.env.*.local

# 用户数据（本地数据库和向量库）
~/.meeting-assistant/

# macOS
.DS_Store

# IDE
.vscode/settings.json
.idea/

# 打包工具临时文件
*.spec
build/
release/
```

> ⚠️ **绝不提交 API Key**：确保 `.env` 文件在 `.gitignore` 中，且 `backend/config.py`（或同类文件）中的密钥通过环境变量读取，不硬编码。

