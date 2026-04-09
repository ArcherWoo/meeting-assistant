# Skill: Excel 分类映射

## 描述
读取一个分类模板 Excel 和一个待分类数据 Excel，根据待分类数据中的名称列，把每一行映射到模板中的一级到五级分类，并输出新的结果 Excel。

## 触发条件
- 关键词: "分类模板", "自动分类", "Excel 分类", "层级分类", "分类映射", "批量分类", "导出 Excel"
- 输入类型: .xlsx / .xls

## 输入参数
- template_import_id: 已导入的分类模板 Excel [type=file] [source=knowledge_import] [required]
- data_import_id: 已导入的待分类数据 Excel [type=file] [source=knowledge_import] [required]
- template_sheet: 分类模板工作表名称 [type=string]
- data_sheet: 待分类数据工作表名称 [type=string]
- name_column: 待分类名称所在列序号，从 1 开始 [type=number] [default=2]
- knowhow_categories: 限制只使用哪些 Know-how 分类规则，多个用英文逗号分隔 [type=string]
- mode: 分类模式 [type=enum] [options=strict|balanced|recall] [default=balanced]
- review_threshold: 低于该置信度时标记人工复核 [type=number] [default=0.55]

## 执行配置
- surface: agent
- preferred_role: executor
- allowed_tools: run_excel_category_mapping
- output_kind: file
- output_sections: 任务摘要 | 结果文件 | 待复核项
- notes: 优先输出实际生成的 Excel 文件 | 业务规则统一来自 Know-how 规则库 | 不要虚构分类路径

## 执行步骤
1. 读取分类模板 Excel，解析一级到五级分类路径
2. 读取待分类数据 Excel，提取指定列的名称
3. 结合当前用户可见的 Know-how 业务规则，对每一行进行候选召回和分类判定
4. 生成结果 Excel，并单独输出待人工复核项

## 依赖工具
- run_excel_category_mapping

## 输出格式
### Excel 分类结果
**处理摘要**: {summary}
**结果文件**: {output_path}
**待复核数量**: {review_count}
