# 压测说明

## 目标

这份文档用于指导当前项目的最小可用压测，重点回答三类问题：

- 普通 chat 的稳定吞吐大概在哪里
- 流式 chat 的首字和总耗时是否健康
- 附件提取加聊天这一整段链路是否稳定，瓶颈更多在提取还是在模型

## 当前压测脚本

- [loadtest_chat.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/loadtest_chat.py)
  - 普通非流式 chat 压测
- [loadtest_chat_stream.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/loadtest_chat_stream.py)
  - 流式 chat 压测
  - 会统计首字耗时和总耗时
- [loadtest_chat_attachment.py](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/loadtest_chat_attachment.py)
  - 附件提取 + chat 压测
  - 会拆开统计附件提取耗时和聊天耗时
- [sample-attachment.txt](/c:/Users/ArcherWoo/Desktop/meeting-assistant-main/meeting-assistant-main/scripts/fixtures/sample-attachment.txt)
  - 一个可直接拿来跑附件压测的示例文件

## 压测前检查

开始前建议确认：

1. 服务已经启动，并且 `/api/health/live` 可访问。
2. 至少有一个可登录用户。
3. 当前 LLM profile 可用。
4. 如果是多实例压测，先看 `/api/health/runtime` 是否已经返回正确的 `cluster` 视角。
5. 如果压的是附件场景，先单次手工调用一次附件提取，确认文件格式被支持。

## 常用命令

### 1. 普通 chat

```powershell
python .\scripts\loadtest_chat.py `
  --base-url http://127.0.0.1:5173 `
  --username admin `
  --password admin123 `
  --model mock-gpt `
  --requests 20 `
  --concurrency 10
```

### 2. 流式 chat

```powershell
python .\scripts\loadtest_chat_stream.py `
  --base-url http://127.0.0.1:5173 `
  --username admin `
  --password admin123 `
  --model mock-gpt `
  --requests 20 `
  --concurrency 10
```

### 3. 附件 chat

```powershell
python .\scripts\loadtest_chat_attachment.py `
  --base-url http://127.0.0.1:5173 `
  --username admin `
  --password admin123 `
  --model mock-gpt `
  --file .\scripts\fixtures\sample-attachment.txt `
  --requests 10 `
  --concurrency 5
```

如果你想压结构化提取链路，而不是默认的聊天快路径，可以额外带：

```powershell
--structured
```

## 输出怎么看

### 普通 chat

重点看：

- 成功数 / 失败数
- 平均耗时
- P95
- 最大耗时

### 流式 chat

除了总耗时，还要重点看：

- 平均首字
- P95 首字

如果首字很稳、总耗时波动很大，通常更像上游模型输出速度问题。  
如果首字也明显抖动，就要继续查检索、排队、连接池和服务端并发。

### 附件 chat

重点看三段：

- 平均附件提取
- 平均聊天耗时
- 总耗时

判断口径：

- 附件提取高，说明文件解析是瓶颈
- 聊天耗时高，说明模型或上下文长度更像瓶颈
- 两者都高，就要分别压附件和纯 chat，再拆开看

## 建议梯度

普通 chat 和流式 chat 可以先从：

1. `10` 请求 / `5` 并发
2. `20` 请求 / `10` 并发
3. `50` 请求 / `20` 并发

附件 chat 建议更保守：

1. `5` 请求 / `2` 并发
2. `10` 请求 / `5` 并发
3. 再根据结果决定是否继续上调

## 多实例压测建议

如果是 Windows 单机多实例：

1. 先确认 `MEETING_ASSISTANT_RUNTIME_COORDINATION=sqlite`
2. 先单实例压一轮，拿到基线
3. 再切到 `2` 实例
4. 最后再切到 `4` 实例

同时建议观察：

- `/api/health/runtime`
- 应用结构化日志
- Nginx 访问日志

## 当前边界

这套压测脚本目前已经覆盖：

- 普通 chat
- 流式 chat
- 附件提取 + chat

还没有覆盖：

- 真正的大文件批量附件
- Agent 长任务
- 流式 chat + 附件 的组合场景
- 多机集群

## 记录建议

每次压测至少记下这些信息：

- 日期和环境
- 部署模式
- worker 或实例数
- 压测脚本类型
- 请求数
- 并发数
- 成功率
- 平均耗时
- P95
- 是否出现 `429`
- `/api/health/runtime` 摘要
