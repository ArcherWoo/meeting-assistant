# 项目结构说明

这份文档只关注“代码放哪里、为什么这样放”，方便后续继续整理时不再把职责混到一起。

## 一级目录

- `src/`：React 前端界面、状态管理、浏览器端 API 封装
- `backend/`：FastAPI 路由、业务服务、测试、内置技能
- `deploy/`：生产部署与守护运行核心逻辑
- `docs/`：开发、产品、部署、协议文档
- `scripts/`：开发辅助脚本

## 前端目录

```text
src/
├─ components/    UI 组件，按业务域拆分
│  └─ auth/          登录页面、管理员面板（LoginPage.tsx、AdminPanel.tsx）
├─ services/      浏览器端 API 调用
│  └─ api.ts         包含 authFetch（自动注入 JWT Token）和所有认证相关 API 函数
├─ stores/        Zustand 状态管理
│  ├─ authStore.ts   持久化登录状态（user、token、login/logout）
│  ├─ chatStore.ts   对话状态
│  └─ appStore.ts    UI 与 LLM 配置
├─ styles/        全局样式
└─ types/         共享类型（包含 User、AuthResponse、Group、AccessGrant）
```

建议继续保持：

- 视图组件放 `components/`
- 网络请求只放 `services/`，所有请求必须过 `authFetch` 而非裸 `fetch`
- 全局状态集中在 `stores/`

## 后端目录

```text
backend/
├─ routers/       API 路由层
│  ├─ auth.py        登录、用户管理、用户组、资源授权 CRUD
│  ├─ chat.py        Chat 流式接口
│  ├─ agent.py       Agent 执行接口
│  ├─ knowledge.py   知识库接口
│  ├─ knowhow.py     Know-how 规则库接口
│  ├─ skills.py      Skill 库接口
│  ├─ settings.py    AI 角色 / 系统设置接口
│  ├─ conversations.py 会话持久化接口
│  └─ ppt.py         PPT 导入接口
├─ services/      业务逻辑与基础设施
│  ├─ auth_service.py   JWT 签发/验证、bcrypt 哈希/校验、get_current_user 依赖
│  ├─ storage.py        SQLite 操作，包含 users/groups/access_grants 表结构
│  └─ 其他服务...
├─ skills/        内置 skill 定义
├─ tests/         后端测试
└─ main.py        FastAPI 入口（已注册 auth 路由）
```

建议继续保持：

- `routers/` 只做参数编排和 HTTP 响应
- `services/` 承担真正业务逻辑
- 新的运行时路径、存储策略优先复用 `services/runtime_paths.py`
- 认证相关逻辑集中在 `services/auth_service.py`，不分散到各路由

## 根目录约定

根目录优先只保留这些内容：

- 启动入口：`start.py`、`deploy.sh`、`deploy.ps1`
- 工具链配置：`package.json`、`vite.config.ts`、`tsconfig*.json`
- 顶层导航：`README.md`

不建议再往根目录新增：

- 业务文档
- 一次性脚本
- 临时调试文件
- 运行时数据文件

## 运行时数据

- 本地开发/用户态数据：默认位于 `~/.meeting-assistant/`
- 服务器部署数据：推荐由 `MEETING_ASSISTANT_HOME` / `MEETING_ASSISTANT_DATA_DIR` 指向独立目录
- 构建产物：`dist/`
- 服务器部署专用虚拟环境：`.server-venv/`
- 服务器部署专用数据：`.server-data/`
