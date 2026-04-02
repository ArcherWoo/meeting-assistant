# Meeting Assistant

一个基于 `React + Vite + FastAPI` 的会议助手项目，当前主线能力包括：

- 智能对话与流式输出
- 附件文本提取与上下文注入
- 知识库导入、检索与 RAG
- Skill / Know-how 管理
- Agent 执行模式

## 最近文档解析升级

- 后端新增统一文档解析层 `backend/services/document_parsing/`，附件提取与知识库导入共用同一套解析链路。
- `XLSX` 现在会保留 merged ranges、多层表头、公式与 `header_path`，不再只是简单摊平文本。
- `DOCX` 现在按块级顺序解析，正文、标题、表格的原始顺序会保留。
- `PDF` 现在优先走 layout-aware 提取；扫描版 PDF 会在可用依赖存在时自动走 OCR，并尝试恢复 OCR 表格。
- `Image` 现在支持图片元数据读取与可选 OCR，能力与 PDF OCR 共用同一套底座。
- 知识库 chunk 现在会落结构化 `metadata_json`，可携带 `sheet/page/row range/OCR 段号/table title` 等定位信息。
- 聊天消息与右侧上下文面板现在会把这些 citation locator 直接展示出来，方便定位命中的来源片段。

## 现在的目录分工

根目录只保留运行入口、构建配置和一级导航，业务代码与文档按职责收拢：

```text
.
├─ backend/               FastAPI 后端
├─ deploy/                生产部署核心逻辑
├─ docs/                  产品、开发、部署、协议文档
├─ scripts/               开发辅助脚本
├─ src/                   React 前端
├─ start.py               开发环境兼容入口
├─ deploy.sh              Linux 部署入口
├─ deploy.ps1             Windows 部署入口
└─ package.json           前端脚本与依赖
```

更细的结构说明见 [docs/architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)。

## 快速开始

### 一键启动开发环境

```bash
python start.py
```

这会同时启动：

- 前端：`http://localhost:4173`
- 后端：`http://127.0.0.1:5173`

启动后需要登录。系统会自动创建默认管理员账户：

| 字段 | 值 |
|------|----|
| 用户名 | `admin` |
| 密码 | `admin123` |

> ⚠️ 生产环境请在首次登录后立即修改默认密码。

### 分开启动

前端：

```bash
npm run dev:frontend
```

后端：

```bash
npm run dev:backend
```

### 常用命令

```bash
npm run build
npm run test:backend
npm run dev:all
```

## 安全说明

- 密码使用 `bcrypt` 单向哈希存储，不可逆向还原。
- 登录后系统签发 JWT Token，有效期默认 24 小时。
- 所有 `/api/*` 接口（除 `/api/health` 和 `/api/auth/login`）必须携带有效 Token。
- 管理员接口（`/api/auth/users`、`/api/auth/groups` 等）额外要求 `system_role=admin`。

## 文档导航

- 总导航：[docs/README.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/README.md)
- 开发说明：[docs/development/DEVELOPMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/DEVELOPMENT.md)
- 项目结构：[docs/architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)
- 服务端部署：[docs/deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)
- 产品文档：[docs/product/PRD.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/PRD.md)

## 端口约定

- 前端开发端口：`4173`
- 后端开发端口：`5173`
- 生产部署默认端口：`5173`

开发环境下，Vite 会把 `/api` 代理到后端；生产环境下，FastAPI 可以直接托管 `dist/` 和 `/api`。
