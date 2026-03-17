"""
Skill 文件解析器 - 将 .skill.md 文件解析为结构化 SkillMeta 对象
遵循 PRD §2.3 / §5½.3 定义的 SKILL.md 文件格式
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SkillMeta:
    """Skill 元数据结构"""
    id: str                          # 文件名（不含扩展名）作为 ID
    name: str = ""                   # Skill 名称（# Skill: xxx）
    description: str = ""            # 描述文本
    keywords: list[str] = field(default_factory=list)   # 触发关键词
    input_types: list[str] = field(default_factory=list) # 输入文件类型
    parameters: list[dict] = field(default_factory=list) # 输入参数列表
    steps: list[str] = field(default_factory=list)       # 执行步骤
    dependencies: list[str] = field(default_factory=list) # 依赖工具
    output_template: str = ""        # 输出格式模板
    source_path: str = ""            # 源文件路径
    is_builtin: bool = False         # 是否内置 Skill


class SkillParser:
    """解析 .skill.md 文件为 SkillMeta 对象"""

    def parse_file(self, file_path: Path) -> SkillMeta:
        """解析单个 Skill 文件"""
        content = file_path.read_text(encoding="utf-8")
        skill_id = file_path.stem.replace(".skill", "")
        is_builtin = "builtin" in str(file_path)
        return self.parse_content(content, skill_id, str(file_path), is_builtin)

    def parse_content(
        self, content: str, skill_id: str,
        source_path: str = "", is_builtin: bool = False,
    ) -> SkillMeta:
        """解析 Skill Markdown 内容为 SkillMeta"""
        meta = SkillMeta(id=skill_id, source_path=source_path, is_builtin=is_builtin)

        # 按二级标题分割各 section
        sections = self._split_sections(content)

        # 解析标题行（# Skill: xxx）
        title_match = re.search(r"^#\s+Skill:\s*(.+)$", content, re.MULTILINE)
        if title_match:
            meta.name = title_match.group(1).strip()

        # 解析各 section
        for heading, body in sections.items():
            heading_lower = heading.lower().strip()
            if "描述" in heading_lower or "description" in heading_lower:
                meta.description = body.strip()
            elif "触发" in heading_lower or "trigger" in heading_lower:
                meta.keywords, meta.input_types = self._parse_triggers(body)
            elif "输入参数" in heading_lower or "input" in heading_lower:
                meta.parameters = self._parse_parameters(body)
            elif "执行步骤" in heading_lower or "step" in heading_lower:
                meta.steps = self._parse_steps(body)
            elif "依赖" in heading_lower or "depend" in heading_lower:
                meta.dependencies = self._parse_dependencies(body)
            elif "输出" in heading_lower or "output" in heading_lower:
                meta.output_template = body.strip()

        return meta

    def _split_sections(self, content: str) -> dict[str, str]:
        """按 ## 标题分割内容为 {heading: body} 字典"""
        sections: dict[str, str] = {}
        current_heading = ""
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("## "):
                if current_heading:
                    sections[current_heading] = "\n".join(current_lines)
                current_heading = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_heading:
            sections[current_heading] = "\n".join(current_lines)
        return sections

    def _parse_triggers(self, body: str) -> tuple[list[str], list[str]]:
        """解析触发条件，返回 (keywords, input_types)"""
        keywords: list[str] = []
        input_types: list[str] = []

        for line in body.split("\n"):
            line = line.strip().lstrip("- ")
            if "关键词" in line or "keyword" in line.lower():
                # 提取引号内的关键词
                keywords = re.findall(r'"([^"]+)"', line)
            elif "输入类型" in line or "input" in line.lower():
                input_types = re.findall(r'\.\w+', line)

        return keywords, input_types

    def _parse_parameters(self, body: str) -> list[dict]:
        """解析输入参数列表"""
        params: list[dict] = []
        for line in body.split("\n"):
            line = line.strip().lstrip("- ")
            if not line or line.startswith("#"):
                continue
            # 格式: name: description（默认: value）
            match = re.match(r"(\w+):\s*(.+?)(?:（默认:\s*(.+?)）)?$", line)
            if match:
                param = {
                    "name": match.group(1),
                    "description": match.group(2).strip(),
                    "required": "必需" in match.group(2),
                }
                if match.group(3):
                    param["default"] = match.group(3).strip()
                params.append(param)
        return params

    def _parse_steps(self, body: str) -> list[str]:
        """解析执行步骤（支持多级缩进，合并子步骤到父步骤）"""
        steps: list[str] = []
        current_step = ""

        for line in body.split("\n"):
            # 匹配顶级步骤（数字开头）
            top_match = re.match(r"^\d+\.\s+(.+)$", line.strip())
            if top_match:
                if current_step:
                    steps.append(current_step.strip())
                current_step = top_match.group(1)
            elif line.strip().startswith("-") or line.strip().startswith("·"):
                # 子步骤追加到当前步骤
                current_step += "\n" + line.strip()
            elif line.strip() and current_step:
                current_step += " " + line.strip()

        if current_step:
            steps.append(current_step.strip())
        return steps

    def _parse_dependencies(self, body: str) -> list[str]:
        """解析依赖工具列表"""
        deps: list[str] = []
        for line in body.split("\n"):
            line = line.strip().lstrip("- ")
            if line and not line.startswith("#"):
                deps.append(line.strip())
        return deps

