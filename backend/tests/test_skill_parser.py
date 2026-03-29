import os
import sys
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.skill_parser import SkillParser


SKILL_CONTENT = """# Skill: Demo Skill

## 描述
Demo description

## 输入参数
- import_id: 已导入文件 [type=file] [source=knowledge_import] [required]
- output_format: 输出格式 [type=enum] [options=markdown|checklist] [default=checklist]

## 执行配置
- surface: agent
- preferred_role: executor
- allowed_tools: extract_file_text, query_knowledge
- output_kind: report
- output_sections: 执行摘要 | 风险点 | 建议动作
- notes: 先提取文件 | 再做检索
"""


class SkillParserTests(unittest.TestCase):
    def test_parse_execution_profile_and_parameter_metadata(self):
        parser = SkillParser()
        skill = parser.parse_content(SKILL_CONTENT, "demo-skill")

        self.assertEqual(skill.execution_profile.surface, "agent")
        self.assertEqual(skill.execution_profile.preferred_role_id, "executor")
        self.assertEqual(skill.execution_profile.allowed_tools, ["extract_file_text", "query_knowledge"])
        self.assertEqual(skill.execution_profile.output_kind, "report")
        self.assertEqual(skill.execution_profile.output_sections, ["执行摘要", "风险点", "建议动作"])
        self.assertEqual(skill.execution_profile.notes, ["先提取文件", "再做检索"])

        self.assertEqual(skill.parameters[0]["type"], "file")
        self.assertEqual(skill.parameters[0]["source"], "knowledge_import")
        self.assertTrue(skill.parameters[0]["required"])
        self.assertEqual(skill.parameters[1]["type"], "enum")
        self.assertEqual(skill.parameters[1]["options"], ["markdown", "checklist"])
        self.assertEqual(skill.parameters[1]["default"], "checklist")


if __name__ == "__main__":
    unittest.main()
