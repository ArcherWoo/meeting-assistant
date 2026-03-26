"""
Skill 管理器 - 发现、加载、索引技能文件
支持内置 Skill（builtin/）和用户自建 Skill（custom/）
"""
import logging
from pathlib import Path
from typing import Optional

from services.runtime_paths import USER_SKILLS_DIR
from services.skill_parser import SkillMeta, SkillParser

logger = logging.getLogger(__name__)

# Skill 文件搜索路径
_BACKEND_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_USER_SKILLS_DIR = USER_SKILLS_DIR


class SkillManager:
    """技能管理器 - 负责 Skill 的发现、加载和索引"""

    def __init__(self) -> None:
        self._parser = SkillParser()
        self._skills: dict[str, SkillMeta] = {}  # id -> SkillMeta
        self._loaded = False

    async def initialize(self) -> None:
        """初始化：扫描并加载所有 Skill 文件"""
        self._skills.clear()
        # 1. 加载内置 Skill
        self._scan_directory(_BACKEND_SKILLS_DIR / "builtin", is_builtin=True)
        # 2. 加载用户自建 Skill（可覆盖内置版本）
        _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        self._scan_directory(_USER_SKILLS_DIR, is_builtin=False)
        self._loaded = True
        logger.info(f"SkillManager 已加载 {len(self._skills)} 个 Skill")

    def _scan_directory(self, directory: Path, is_builtin: bool) -> None:
        """扫描目录下所有 .skill.md 文件"""
        if not directory.exists():
            return
        for file_path in directory.rglob("*.skill.md"):
            try:
                skill = self._parser.parse_file(file_path)
                skill.is_builtin = is_builtin
                self._skills[skill.id] = skill
                logger.debug(f"已加载 Skill: {skill.id} ({skill.name})")
            except Exception as e:
                logger.warning(f"加载 Skill 失败: {file_path} - {e}")

    def list_skills(self, builtin_only: bool = False) -> list[SkillMeta]:
        """列出所有已加载的 Skill"""
        skills = list(self._skills.values())
        if builtin_only:
            skills = [s for s in skills if s.is_builtin]
        return skills

    def get_skill(self, skill_id: str) -> Optional[SkillMeta]:
        """根据 ID 获取 Skill"""
        return self._skills.get(skill_id)

    def get_skill_summary(self) -> list[dict]:
        """获取所有 Skill 的摘要信息（用于 Agent System Prompt）"""
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
                "input_types": s.input_types,
            }
            for s in self._skills.values()
        ]

    async def reload(self) -> None:
        """重新加载所有 Skill（热加载）"""
        await self.initialize()


# 全局单例
skill_manager = SkillManager()
