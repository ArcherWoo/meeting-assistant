# Chat Completions SSE Metadata 示例

这份文档对应当前 `/api/chat/completions` 的实际前端消费协议，重点是尾部两个事件：

- `context_metadata`
- `skill_suggestion`

它们都必须出现在 `data: [DONE]` 之前。

## 原始流样例

完整原始流见：

- `docs/chat-completions-context-example.sse`

## 事件顺序

典型顺序如下：

1. 常规 OpenAI 风格增量 chunk
2. `context_metadata`
3. `skill_suggestion`
4. `data: [DONE]`

## `context_metadata` 关键字段

- `knowledge_count` / `knowhow_count` / `skill_count`
- `summary`
- `citations`

其中 `citations` 现在支持更细粒度的定位信息：

- `file_name`: 来源文件名
- `title`: 片段标题，例如 `第2页 · 表格片段`
- `location`: 更细位置，例如 `片段 #7 · 字符 121-268`
- `page`: 页码
- `chunk_type`: `text` / `table` / `note`
- `chunk_index`: 片段序号
- `char_start` / `char_end`: 文本分块字符区间

## 协议补充字段

`context_metadata.sources` 还会携带以下兼容增强字段：

- `schema_version`: 当前为 `2`
- `truncated`: 当前注入到 prompt 的上下文是否被预算裁剪过
- `retrieved_summary`: 裁剪前检索结果摘要
- `retrieved_knowledge_count` / `retrieved_knowhow_count` / `retrieved_skill_count`
- `retrieved_citations`: 裁剪前的 citation 列表

这意味着：

- `sources.*` 默认表示真正注入到 prompt 的上下文
- `retrieved_*` 表示裁剪前原始检索结果

`skill_suggestion` 事件也升级为兼容增强版：

- `schema_version`: 当前为 `2`
- `matched_keywords`: 触发该 Skill 推荐的命中关键词

## 前端展示约定

聊天气泡中的 citation 卡片按固定结构展示：

- 文件名 / 来源
- 位置
- 摘要

这样即使不同来源类型共用一套卡片组件，用户也能稳定看到“来源对象 + 定位信息 + 摘要内容”。

## Citation Locator 扩展

随着统一文档解析与结构化 chunk 落地，`citations` 现在还可能携带更丰富的定位字段，用于前端 badge 展示与调试：

- `sheet`: Excel 工作表名
- `row_start` / `row_end`: 表格或区域的起止行
- `story`: 兼容富文本或分段来源的逻辑分区
- `source`: 解析来源类型，例如 `ocr` / `layout` / `table`
- `ocr_segment_index`: OCR 切块序号
- `table_title`: 表格标题或推断出的表主题

这些字段目前主要来自：

- `knowledge_chunks.metadata_json`
- SQLite / 向量检索后的 locator 回填
- `context_assembler` 在 citation 阶段的统一格式化

前端目前会在以下位置把它们渲染为可见定位标签：

- `src/components/chat/MessageBubble.tsx`
- `src/components/layout/ContextPanel.tsx`

典型效果包括：

- `第 3 页`
- `报价汇总`
- `行 2-18`
- `OCR #4`
- `表格: 供应商报价`
