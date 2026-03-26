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
├─ services/      浏览器端 API 调用
├─ stores/        Zustand 状态管理
├─ styles/        全局样式
└─ types/         共享类型
```

建议继续保持：

- 视图组件放 `components/`
- 网络请求只放 `services/`
- 全局状态集中在 `stores/`

## 后端目录

```text
backend/
├─ routers/       API 路由层
├─ services/      业务逻辑与基础设施
├─ skills/        内置 skill 定义
├─ tests/         后端测试
└─ main.py        FastAPI 入口
```

建议继续保持：

- `routers/` 只做参数编排和 HTTP 响应
- `services/` 承担真正业务逻辑
- 新的运行时路径、存储策略优先复用 `services/runtime_paths.py`

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
