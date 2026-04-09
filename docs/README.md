# 文档导航

当前文档按职责分成 5 类，后续新增内容也建议沿着这个结构补充：

- `architecture/`：项目结构、模块边界、目录约定
- `development/`：开发说明、模块设计、协作记录
- `deployment/`：部署、运维、运行方式
- `product/`：PRD、需求背景、业务目标
- `reference/`：接口协议、SSE 示例、补充资料

## 入口文档

- 项目结构：[architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)
- 开发说明：[development/DEVELOPMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/DEVELOPMENT.md)
- 改造蓝图：[development/CHAT_AGENT_REFACTOR_BLUEPRINT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/CHAT_AGENT_REFACTOR_BLUEPRINT.md)
- 部署说明：[deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)
- 压测说明：[deployment/LOAD_TESTING.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/LOAD_TESTING.md)
- 产品文档：[product/PRD.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/PRD.md)
- 今日状态更新：[2026-04-07_STATUS_UPDATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/2026-04-07_STATUS_UPDATE.md)
- 今日开发记录：[development/2026-04-07_CHAT_KNOWHOW_CONVERSATION_UPDATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/2026-04-07_CHAT_KNOWHOW_CONVERSATION_UPDATE.md)
- 今日产品口径：[product/2026-04-07_PERMISSION_POLICY.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/2026-04-07_PERMISSION_POLICY.md)
- 当前状态：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- SSE 元数据说明：[reference/SSE_CONTEXT_METADATA.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/reference/SSE_CONTEXT_METADATA.md)
- SSE 示例：[reference/chat-completions-context-example.sse](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/reference/chat-completions-context-example.sse)

## 最近更新关注点

- 2026-04-09：生产部署新增 `deploy.bat`，Linux `deploy.sh` 补齐 `--prepare / --foreground / --stop` 入口，生产脚本默认自动探测公司 pip 镜像并回填 `deploy/server.env`：[deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)
- 2026-04-09：开发启动脚本与生产部署脚本已统一成干净中文输出；Windows 生产部署已支持自动接管 Nginx，生产环境也新增了正式的优雅关闭入口：[../README.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/README.md)
- 文档解析与 OCR 当前基线：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- 聊天首回体验、实时 Markdown、附件分析预览：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- Chat 下 Knowhow 智能路由、分类召回与 LLM 判定接线：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- Knowhow Phase 2：结构化分类画像、规则元数据与 LLM 二次判定：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- Knowhow 录入体验收敛：前端保持极简，规则元数据与分类画像改为后端自动提炼：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- 2026-04-07：Chat 下 Know-how 权限收口、组内 Know-how manager 作用域、规则库摘要按可见范围生成：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- 2026-04-07：会话隐私口径调整为所有人只看自己的对话：[CURRENT_STATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/CURRENT_STATE.md)
- 2026-04-07：干净中文状态记录：[2026-04-07_STATUS_UPDATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/2026-04-07_STATUS_UPDATE.md)
- 2026-04-07：干净中文开发记录：[development/2026-04-07_CHAT_KNOWHOW_CONVERSATION_UPDATE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/2026-04-07_CHAT_KNOWHOW_CONVERSATION_UPDATE.md)
- 2026-04-07：干净中文产品口径：[product/2026-04-07_PERMISSION_POLICY.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/2026-04-07_PERMISSION_POLICY.md)
- 2026-04-08：Phase 2 部署与并发治理更新，覆盖健康检查、结构化日志、Windows 多实例部署、Nginx rendered 配置与压测说明：[deployment/SERVER_DEPLOYMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/deployment/SERVER_DEPLOYMENT.md)
- 开发落地说明：[development/DEVELOPMENT.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/development/DEVELOPMENT.md)
- 项目结构补充：[architecture/PROJECT_STRUCTURE.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/architecture/PROJECT_STRUCTURE.md)
- 产品侧要求与验收口径：[product/PRD.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/product/PRD.md)
- SSE / citation 元数据：[reference/SSE_CONTEXT_METADATA.md](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/docs/reference/SSE_CONTEXT_METADATA.md)
