"""
Skill 文件解析器 - 将 .skill.md 文件解析为结构化 SkillMeta 对象
遵循 PRD 中约定的 SKILL.md 文件格式，并扩展支持 execution profile。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillExecutionProfile:
    """Skill 执行配置 - 声明推荐角色、工具白名单和输出预期"""

    surface: str = "agent"
    preferred_role_id: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    output_kind: str = ""
    output_sections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class SkillMeta:
    """Skill 元数据结构"""

    id: str
    name: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    input_types: list[str] = field(default_factory=list)
    parameters: list[dict] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    output_template: str = ""
    execution_profile: SkillExecutionProfile = field(default_factory=SkillExecutionProfile)
    source_path: str = ""
    is_builtin: bool = False


class SkillParser:
    """解析 .skill.md 文件为 SkillMeta 对象"""

    def parse_file(self, file_path: Path) -> SkillMeta:
        content = file_path.read_text(encoding="utf-8")
        skill_id = file_path.stem.replace(".skill", "")
        is_builtin = "builtin" in str(file_path)
        return self.parse_content(content, skill_id, str(file_path), is_builtin)

    def parse_content(
        self,
        content: str,
        skill_id: str,
        source_path: str = "",
        is_builtin: bool = False,
    ) -> SkillMeta:
        meta = SkillMeta(id=skill_id, source_path=source_path, is_builtin=is_builtin)
        sections = self._split_sections(content)

        title_match = re.search(r"^#\s+Skill:\s*(.+)$", content, re.MULTILINE)
        if title_match:
            meta.name = title_match.group(1).strip()

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
            elif "输出格式" in heading_lower or "output" in heading_lower:
                meta.output_template = body.strip()
            elif "执行配置" in heading_lower or "execution profile" in heading_lower:
                meta.execution_profile = self._parse_execution_profile(body)

        return meta

    def _split_sections(self, content: str) -> dict[str, str]:
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
        keywords: list[str] = []
        input_types: list[str] = []

        for raw_line in body.split("\n"):
            line = raw_line.strip().lstrip("- ")
            if "关键词" in line or "keyword" in line.lower():
                keywords = re.findall(r'"([^"]+)"', line)
            elif "输入类型" in line or "input" in line.lower():
                input_types = re.findall(r"\.\w+", line)

        return keywords, input_types

    def _parse_parameters(self, body: str) -> list[dict]:
        params: list[dict] = []
        for raw_line in body.split("\n"):
            line = raw_line.strip().lstrip("- ")
            if not line or line.startswith("#") or ":" not in line:
                continue

            name, raw_desc = line.split(":", 1)
            name = name.strip()
            if not name:
                continue

            description = raw_desc.strip()
            tags = re.findall(r"\[([^\]]+)\]", description)
            clean_description = re.sub(r"\[[^\]]+\]", "", description).strip()

            param = {
                "name": name,
                "type": "string",
                "required": "必需" in description or "必填" in description or "[required]" in description.lower(),
                "description": clean_description,
            }

            legacy_default = re.search(r"(?:默认|榛樿)\s*[:：]?\s*([^\)）]+)", description)
            if legacy_default:
                param["default"] = legacy_default.group(1).strip()

            for tag in tags:
                normalized = tag.strip()
                lower_tag = normalized.lower()
                if "=" in normalized:
                    key, raw_value = normalized.split("=", 1)
                    key = key.strip().lower()
                    value = raw_value.strip()
                    if key == "type" and value:
                        param["type"] = value
                    elif key == "default" and value:
                        param["default"] = value
                    elif key == "source" and value:
                        param["source"] = value
                    elif key == "options":
                        options = [item.strip() for item in re.split(r"[|,]", value) if item.strip()]
                        if options:
                            param["options"] = options
                            if param["type"] == "string":
                                param["type"] = "enum"
                elif lower_tag == "required":
                    param["required"] = True

            params.append(param)
        return params

    def _parse_steps(self, body: str) -> list[str]:
        steps: list[str] = []
        current_step = ""

        for raw_line in body.split("\n"):
            top_match = re.match(r"^\d+\.\s+(.+)$", raw_line.strip())
            if top_match:
                if current_step:
                    steps.append(current_step.strip())
                current_step = top_match.group(1)
            elif raw_line.strip().startswith("-") or raw_line.strip().startswith("•"):
                current_step += "\n" + raw_line.strip()
            elif raw_line.strip() and current_step:
                current_step += " " + raw_line.strip()

        if current_step:
            steps.append(current_step.strip())
        return steps

    def _parse_dependencies(self, body: str) -> list[str]:
        deps: list[str] = []
        for raw_line in body.split("\n"):
            line = raw_line.strip().lstrip("- ")
            if line and not line.startswith("#"):
                deps.append(line)
        return deps

    def _parse_execution_profile(self, body: str) -> SkillExecutionProfile:
        profile = SkillExecutionProfile()
        for raw_line in body.split("\n"):
            line = raw_line.strip().lstrip("- ")
            if not line or line.startswith("#") or ":" not in line:
                continue

            key, raw_value = line.split(":", 1)
            key = key.strip().lower()
            value = raw_value.strip()
            if not value:
                continue

            if key in {"surface", "surface_mode"}:
                profile.surface = value
            elif key in {"preferred_role", "preferred_role_id", "role"}:
                profile.preferred_role_id = value
            elif key in {"allowed_tools", "tools"}:
                profile.allowed_tools = [item.strip() for item in re.split(r"[|,]", value) if item.strip()]
            elif key in {"output_kind", "result_kind"}:
                profile.output_kind = value
            elif key in {"output_sections", "sections"}:
                profile.output_sections = [item.strip() for item in re.split(r"[|,]", value) if item.strip()]
            elif key in {"notes", "guidance"}:
                profile.notes = [item.strip() for item in re.split(r"[|,]", value) if item.strip()]
        return profile
