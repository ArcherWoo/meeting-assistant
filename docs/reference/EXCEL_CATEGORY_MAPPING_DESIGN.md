# Excel 分类映射设计

## 目标

把“分类模板 Excel + 待分类数据 Excel -> 分类结果 Excel”做成一个可复用的 Agent/Skill 能力，并且：

- 业务分类规则统一归口到 `Know-how` 规则库
- 优先复用现有 `Skill / Agent / Excel 解析 / Know-how 权限` 能力
- 输出真实 `.xlsx` 文件，而不是只输出 Markdown

## 当前实现

### 入口

- 内置 Skill：`backend/skills/builtin/excel-category-mapping.skill.md`
- Agent tool：`run_excel_category_mapping`

### 核心执行器

- 分类执行服务：`backend/services/classification_service.py`

### 规则来源

- 业务规则来自当前用户可见的 `Know-how` 规则
- 会复用现有的：
  - `trigger_terms`
  - `exclude_terms`
  - `applies_when`
  - `examples`
  - `retrieval_summary`
  - `retrieval_queries`

### 执行流程

1. 读取分类模板 Excel，解析一级到五级分类路径
2. 读取待分类数据 Excel，提取指定名称列
3. 对名称去重，减少重复分类调用
4. 基于模板路径做候选召回
5. 用当前用户可见的 Know-how 规则做规则增强
6. 高置信命中走启发式直达
7. 模糊样本在候选集内走 LLM 结构化判定
8. 输出结果 Excel，并分出待人工复核 Sheet

## 为什么不是纯 Chat

纯 Chat 更适合解释和追问，不适合这种批量结构化任务：

- 难稳定输出 Excel
- 批处理成本高
- prompt 容易越来越重
- 不利于复核和重复执行

所以当前采用：

- `Agent + Skill` 作为任务入口
- `classification_service` 作为真实执行器
- `Know-how` 作为业务规则层

## 输入约定

当前第一版 Skill 参数：

- `template_path`
- `data_path`
- `template_sheet`
- `data_sheet`
- `name_column`
- `knowhow_categories`
- `mode`
- `review_threshold`

说明：

- 第一版直接读取原始 Excel 文件路径，优先保证表格结构稳定
- 后续可以继续把“附件 / 知识库导入项”接成输入源，但不把知识库文本块当主数据源

## 输出约定

结果 Excel 默认写入：

- `data/classification_outputs/`

或调用方显式指定的输出目录。

结果文件包含：

- `分类结果`
- `待人工复核`
- `任务摘要`

## Know-how 的推荐用法

分类业务规则建议继续放在 Know-how 中，按领域或模板族组织，例如：

- `半导体设备分类`
- `采购物料分类`
- `法务合同分类`

推荐规则类型：

- 关键词优先
- 排除规则
- 同义词 / 别名
- 层级约束
- 人工复核条件

## 当前边界

- 第一版结果文件已生成，但前端还只是展示结果文件路径，没有下载按钮
- 第一版主输入是文件路径，不是浏览器上传后的临时文件
- 知识库可作为后续增强层，但当前不作为主分类数据源

## 后续建议

1. 给 Agent 产物补文件下载入口
2. 给 Agent 参数面板补“上传模板 / 上传待分类数据”能力
3. 引入历史分类样本作为知识库增强召回
4. 增加人工复核回写，形成可学习的分类经验
