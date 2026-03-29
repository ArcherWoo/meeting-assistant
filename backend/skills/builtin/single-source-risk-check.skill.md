# Skill: 单一来源风险核查

## 描述
围绕单一来源采购场景，判断材料中是否已经充分说明唯一性、必要性和风险控制措施，并给出补充建议。

## 触发条件
- 关键词: "单一来源", "唯一供应商", "单一来源风险", "唯一性说明", "单一来源说明"
- 输入类型: .pdf .docx .pptx

## 输入参数
- import_id: 已导入说明材料 [type=file] [source=knowledge_import]
- strict_mode: 是否按严格模式判断 [type=boolean] [default=true]

## 执行配置
- surface: agent
- preferred_role: executor
- allowed_tools: extract_file_text, search_knowhow_rules, query_knowledge
- output_kind: risk-report
- output_sections: 结论 | 缺口 | 风险等级 | 建议补充
- notes: 优先检索单一来源相关规则 | 无法证明唯一性时不要给出通过结论

## 执行步骤
1. 提取单一来源说明材料
2. 检索单一来源相关规则、风险要求和补充说明标准
3. 对照材料逐项判断是否覆盖唯一性、必要性和风险控制
4. 输出风险等级与补充建议

## 依赖工具
- extract_file_text
- search_knowhow_rules
- query_knowledge

## 输出格式
### 单一来源风险核查报告
#### 一、结论
#### 二、关键缺口
#### 三、风险等级
#### 四、建议补充
