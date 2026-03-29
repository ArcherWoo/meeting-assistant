# Skill: 采购会前材料预审

## 描述
针对采购方案、报价材料或立项说明进行会前预审，优先核查价格合理性、规则风险、材料缺口和待补充事项，输出结构化预审结论。

## 触发条件
- 关键词: "采购预审", "会前审查", "采购分析", "预审报告", "审查采购材料", "采购审核"
- 输入类型: .pptx .pdf .docx

## 输入参数
- import_id: 已导入采购文件 [type=file] [source=knowledge_import]
- check_history: 是否对比历史知识库 [type=boolean] [default=true]
- check_knowhow: 是否检查规则库 [type=boolean] [default=true]
- output_format: 输出格式 [type=enum] [options=markdown|checklist|report] [default=report]

## 执行配置
- surface: agent
- preferred_role: executor
- allowed_tools: get_skill_definition, extract_file_text, query_knowledge, search_knowhow_rules
- output_kind: report
- output_sections: 执行摘要 | 风险点 | 证据引用 | 下一步建议
- notes: 优先抽取文件原文后再判断 | 涉及价格或风险结论时优先引用知识库或规则库

## 执行步骤
1. 读取并提取采购文件的核心内容
2. 如果 check_history=true，则检索知识库中的历史案例、报价或相关文档
3. 如果 check_knowhow=true，则检索 Know-how 规则库中的审批、合规和风险要求
4. 综合材料内容、知识证据与规则依据，形成预审结论

## 依赖工具
- extract_file_text
- query_knowledge
- search_knowhow_rules

## 输出格式
### 采购会前预审报告
**文件**: {filename}
**预审结论**: 通过 / 需关注 / 建议补充

#### 一、执行摘要
#### 二、核心风险点
#### 三、证据引用
#### 四、建议补充动作
