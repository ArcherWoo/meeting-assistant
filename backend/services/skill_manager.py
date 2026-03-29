"""
Skill 管理器 - 发现、加载、索引技能文件
支持内置 Skill（builtin/）和用户自建 Skill（custom/）
"""
import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import asdict

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
        self._builtin_sources: dict[str, Path] = {}
        self._deleted_builtin_ids: set[str] = set()
        self._loaded = False

    async def initialize(self) -> None:
        """初始化：扫描并加载所有 Skill 文件"""
        self._skills.clear()
        self._builtin_sources.clear()
        self._deleted_builtin_ids = self._load_deleted_builtin_ids()
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
                if is_builtin:
                    self._builtin_sources[skill.id] = file_path
                    if skill.id in self._deleted_builtin_ids:
                        continue
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

    def _tombstones_path(self) -> Path:
        return _USER_SKILLS_DIR / ".deleted_builtin_skills.json"

    def _load_deleted_builtin_ids(self) -> set[str]:
        tombstones_path = self._tombstones_path()
        if not tombstones_path.exists():
            return set()
        try:
            raw = json.loads(tombstones_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    async def _save_deleted_builtin_ids(self) -> None:
        _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        tombstones_path = self._tombstones_path()
        if not self._deleted_builtin_ids:
            tombstones_path.unlink(missing_ok=True)
            return
        tombstones_path.write_text(
            json.dumps(sorted(self._deleted_builtin_ids), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def mark_builtin_deleted(self, skill_id: str) -> None:
        self._deleted_builtin_ids.add(skill_id)
        await self._save_deleted_builtin_ids()

    async def clear_builtin_deleted(self, skill_id: str) -> None:
        if skill_id in self._deleted_builtin_ids:
            self._deleted_builtin_ids.remove(skill_id)
            await self._save_deleted_builtin_ids()

    def has_builtin_skill(self, skill_id: str) -> bool:
        return skill_id in self._builtin_sources

    def get_skill_summary(self) -> list[dict]:
        """获取所有 Skill 的摘要信息（用于 Agent System Prompt）"""
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
                "input_types": s.input_types,
                "execution_profile": asdict(s.execution_profile),
            }
            for s in self._skills.values()
        ]

    async def reload(self) -> None:
        """重新加载所有 Skill（热加载）"""
        await self.initialize()


# 全局单例
skill_manager = SkillManager()
