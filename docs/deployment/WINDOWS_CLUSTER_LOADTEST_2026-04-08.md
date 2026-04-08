# Windows 多实例压测记录（2026-04-08）

## 这轮做了什么

这轮主要验证两件事：

- Windows 下通过 `deploy/service_runner.py` 拉起多实例后，聊天链路是否真的稳定
- `/api/health/runtime` 里的应用级指标，是否已经能聚合成整机视角，而不是只看当前实例

## 先修掉的两个 blocker

在正式重跑压测前，先收掉了两个真实问题：

1. 启动默认数据竞争

- 4 实例同时启动时，默认工作区、内置角色、默认管理员会并发写 SQLite
- 现象是启动阶段出现 `database is locked`、`UNIQUE constraint failed: roles.id`
- 修复方式是把启动默认数据收进单机共享租约，只允许一个实例负责种子初始化，其他实例等待默认数据就绪

2. 运行指标写入竞争

- 4 实例高并发 chat 时，`publish_runtime_metrics()` 会把运行指标写回 SQLite
- 现象是本来应该正常返回的请求，被 `runtime_application_metrics` 写锁打成 `500`
- 修复方式是把运行指标读写改成独立连接，并增加轻量重试；即使指标写失败，也不再反向拖垮 chat 请求

## 测试环境

- 平台：Windows 10
- Python：3.10.11
- 启动器：`deploy/service_runner.py`
- 协调后端：`sqlite`
- Mock LLM：`http://127.0.0.1:5190/v1`
- Mock 模型：`mock-gpt`

## 双实例基线

### 运行参数

- 端口：`5212`、`5213`
- 实例数：`2`
- 每实例请求数：`12`
- 每实例并发：`3`
- 总请求数：`24`

### 结果

- `5212`：`12/12` 成功，平均 `405.08 ms`，P95 `422 ms`，最大 `454 ms`
- `5213`：`12/12` 成功，平均 `404.58 ms`，P95 `430 ms`，最大 `439 ms`

### 聚合指标

从 `/api/health/runtime` 读取到：

- `runtime_usage.application.scope = "cluster"`
- `runtime_usage.application.instance_count = 2`
- `chat_completed_total = 24`
- `chat_failed_total = 0`

结论：双实例链路已经稳定，聚合视图也是生效的。

## 四实例基线

### 运行参数

- 端口：`5242`、`5243`、`5244`、`5245`
- 实例数：`4`
- 每实例请求数：`12`
- 每实例并发：`3`
- 总请求数：`48`

为了让这轮压测测的是“系统稳定性”，而不是“默认限流阈值”，本轮运行环境额外设置了：

- `MEETING_ASSISTANT_LLM_GLOBAL_CONCURRENCY=16`
- `MEETING_ASSISTANT_LLM_STREAM_CONCURRENCY=12`
- `MEETING_ASSISTANT_LLM_LIGHTWEIGHT_CONCURRENCY=12`
- `MEETING_ASSISTANT_LLM_PER_USER_CONCURRENCY=3`

### 结果

- `5242`：`12/12` 成功，平均 `507.17 ms`，P95 `753 ms`，最大 `946 ms`
- `5243`：`12/12` 成功，平均 `587.17 ms`，P95 `905 ms`，最大 `1046 ms`
- `5244`：`12/12` 成功，平均 `565.92 ms`，P95 `735 ms`，最大 `1201 ms`
- `5245`：`12/12` 成功，平均 `531.42 ms`，P95 `714 ms`，最大 `911 ms`

整轮结果：

- 总请求数：`48`
- 成功数：`48`
- 失败数：`0`

### 聚合指标

从 `5242` 的 `/api/health/runtime` 读取到：

- `runtime_usage.application.scope = "cluster"`
- `runtime_usage.application.instance_count = 4`
- `chat_started_total = 48`
- `chat_completed_total = 48`
- `chat_failed_total = 0`
- `chat_rejected_total = 0`
- `chat_end_to_end_ms` 平均 `488.1 ms`
- `chat_llm_total_ms` 平均 `485.5 ms`
- `chat_retrieval_ms` 平均 `1.44 ms`

## 当前结论

截至 `2026-04-08`，Windows 多实例这一段可以明确写成：

- 双实例 chat 压测已稳定通过
- 四实例 chat 压测已稳定通过
- 启动默认数据竞争已修复
- 运行指标写锁导致的 `500` 已修复
- `/api/health/runtime` 的应用级视图已经是整机聚合结果

## 仍然保留的边界

虽然这轮已经拿到了可信基线，但还要明确几个边界：

- 这仍然是单机多实例，不是多机集群
- 当前协调后端仍是 SQLite，更高写入规模下仍要继续观察
- 这轮压测覆盖的是普通 chat 非流式请求，还没有覆盖附件、Agent、长流式混合场景

## 下一步建议

下一步优先做这三件事：

1. 把这轮参数和结果同步到总方案文档，作为 Phase 2 的正式阶段性结论
2. 增加流式 chat、附件 chat、Agent 三类压测样本
3. 评估是否需要进入下一阶段的数据层升级，例如 PostgreSQL
