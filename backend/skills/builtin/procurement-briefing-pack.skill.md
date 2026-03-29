# Skill: 采购汇报要点整理

## 描述
根据已导入采购材料，提炼适合会议汇报的核心事实、风险提示和待拍板事项，形成简洁的汇报提纲。

## 触发条件
- 关键词: "汇报要点", "采购汇报", "会议提纲", "老板关注点", "拍板事项"
- 输入类型: .pptx .pdf .docx

## 输入参数
- import_id: 已导入采购材料 [type=file] [source=knowledge_import]
- audience: 汇报对象 [type=enum] [options=老板|采购负责人|评审会] [default=老板]

## 执行配置
- surface: agent
- preferred_role: builder
- allowed_tools: extract_file_text, query_knowledge, search_knowhow_rules
- output_kind: briefing
- output_sections: 一页摘要 | 关键数据 | 风险提醒 | 待决策事项
- notes: 保持表达简洁 | 对关键结论尽量补引用依据

## 执行步骤
1. 提取采购材料文本
2. 如有必要补检索历史知识或相关规则
3. 提炼可用于会议汇报的核心要点
4. 输出适合直接汇报的结构化提纲

## 依赖工具
- extract_file_text
- query_knowledge
- search_knowhow_rules

## 输出格式
### 采购汇报提纲
#### 一、一页摘要
#### 二、关键数据
#### 三、风险提醒
#### 四、待决策事项
