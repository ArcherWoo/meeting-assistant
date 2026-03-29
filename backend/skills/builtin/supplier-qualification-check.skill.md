# Skill: 供应商资质核查

## 描述
针对供应商相关材料进行资质与合规快速核查，确认是否存在证照缺失、资格不清、规则不匹配等问题。

## 触发条件
- 关键词: "供应商资质", "资质核查", "资格审查", "合规核查", "证照检查"
- 输入类型: .pdf .docx .pptx

## 输入参数
- import_id: 已导入供应商材料 [type=file] [source=knowledge_import]
- focus_area: 关注重点 [type=enum] [options=资质完整性|合规风险|准入条件] [default=资质完整性]
- output_format: 输出格式 [type=enum] [options=markdown|checklist] [default=checklist]

## 执行配置
- surface: agent
- preferred_role: executor
- allowed_tools: extract_file_text, search_knowhow_rules, query_knowledge
- output_kind: checklist
- output_sections: 资质判断 | 缺失项 | 风险说明 | 处理建议
- notes: 规则判断优先引用 knowhow | 缺证或不清晰项要明确写出“依据不足”

## 执行步骤
1. 提取供应商材料文本
2. 检索相关准入、资质和合规规则
3. 结合已有知识材料判断资质是否充分
4. 形成核查清单和风险说明

## 依赖工具
- extract_file_text
- search_knowhow_rules
- query_knowledge

## 输出格式
### 供应商资质核查清单
#### 一、资质判断
#### 二、缺失项
#### 三、风险说明
#### 四、处理建议
