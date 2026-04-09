# Chat Knowhow 评测说明

这套评测用来量化 `chat -> retrieval planner -> knowhow router -> knowhow rules` 这条链路，而不是只靠体感判断“是不是更聪明了”。

## 文件

- 评测脚本：[evaluate_chat_knowhow.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/evaluate_chat_knowhow.py)
- 评测集：[knowhow-eval-cases.json](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/fixtures/knowhow-eval-cases.json)

## 评测内容

脚本会在临时 SQLite 数据库里：

1. 初始化后端存储和默认管理员
2. 写入一组稳定的 knowhow 样本规则
3. 逐条跑评测问句
4. 量化这些指标

- `通过率`
- `planner 是否选择 knowhow`
- `最终是否真正命中预期规则`
- `library summary` 是否识别正确
- `平均总耗时 / P95`
- `平均规划耗时`
- `平均 knowhow 耗时`
- `累计 LLM 调用数`

## 运行方式

### 1. 纯启发式模式

不传 LLM 配置，会只跑当前本地的启发式和非 LLM 路径：

```powershell
python .\scripts\evaluate_chat_knowhow.py
```

### 2. 带真实 LLM 配置

如果要评估真实线上路由质量和额外延迟，可以带上配置：

```powershell
python .\scripts\evaluate_chat_knowhow.py `
  --api-url https://your-openai-compatible-endpoint/v1 `
  --api-key sk-xxx `
  --model deepseek-chat
```

### 3. 输出 Markdown 报告

```powershell
python .\scripts\evaluate_chat_knowhow.py `
  --markdown-out .\docs\reference\CHAT_KNOWHOW_EVAL_REPORT.md
```

## 评测集说明

当前评测集覆盖：

- 寒暄 / 翻译 / 润色等不应触发 knowhow 的样本
- 供应商资质、单一来源、报价合理性、付款条款、交付计划等规则命中样本
- 规则库统计 / 分类盘点这类 library summary 样本
- 1 条 `requires_llm=true` 的改写问法样本，用于观察 LLM route 能否提升召回

如果不传 LLM 配置，这类 `requires_llm=true` 样本会被标记为 `skipped`，不会污染启发式基线。

## 推荐使用方式

每次你继续调这条链路时，建议固定做两轮：

1. 先跑启发式基线
2. 再跑真实 LLM 配置

这样能区分：

- 是本地候选生成变准了
- 还是只是 LLM 帮忙兜住了
- 以及额外 LLM 判断到底带来了多少延迟
