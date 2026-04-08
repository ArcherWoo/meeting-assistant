import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import skills as skills_router
from services.skill_manager import skill_manager


DEMO_SKILL = """# Skill: Demo Skill
## Description
Demo description
## Trigger
- keyword: "demo"
## Execution Profile
- preferred_role: executor
- allowed_tools: extract_file_text, query_knowledge
## Steps
1. do something
"""


class SkillsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-test-data" / f"skills-router-{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        root = self.temp_dir
        self.backend_skills_dir = root / "backend_skills"
        self.builtin_dir = self.backend_skills_dir / "builtin"
        self.user_skills_dir = root / "user_skills"
        self.builtin_dir.mkdir(parents=True, exist_ok=True)
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)

        self.patchers = [
            patch("services.skill_manager._BACKEND_SKILLS_DIR", self.backend_skills_dir),
            patch("services.skill_manager._USER_SKILLS_DIR", self.user_skills_dir),
            patch("routers.skills._BACKEND_SKILLS_DIR", self.backend_skills_dir),
            patch("routers.skills._USER_SKILLS_DIR", self.user_skills_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

        skill_manager._skills.clear()
        skill_manager._builtin_sources.clear()
        skill_manager._deleted_builtin_ids = set()

    async def asyncTearDown(self):
        skill_manager._skills.clear()
        skill_manager._builtin_sources.clear()
        skill_manager._deleted_builtin_ids = set()
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_delete_builtin_skill_hides_it_without_removing_source_file(self):
        builtin_file = self.builtin_dir / "demo.skill.md"
        builtin_file.write_text(DEMO_SKILL, encoding="utf-8")
        await skill_manager.reload()

        listed = await skills_router.list_skills()
        self.assertEqual(listed["skills"][0]["execution_profile"]["preferred_role_id"], "executor")

        result = await skills_router.delete_skill("demo")

        self.assertEqual(result["deletion_mode"], "builtin_tombstone")
        self.assertTrue(builtin_file.exists())
        self.assertIsNone(skill_manager.get_skill("demo"))

        tombstones = self.user_skills_dir / ".deleted_builtin_skills.json"
        self.assertTrue(tombstones.exists())
        self.assertIn("demo", tombstones.read_text(encoding="utf-8"))

    async def test_delete_user_override_of_builtin_removes_override_and_hides_builtin_fallback(self):
        builtin_file = self.builtin_dir / "demo.skill.md"
        builtin_file.write_text(DEMO_SKILL, encoding="utf-8")

        override_file = self.user_skills_dir / "demo.skill.md"
        override_file.write_text(DEMO_SKILL.replace("Demo description", "Override description"), encoding="utf-8")

        await skill_manager.reload()
        skill_before_delete = skill_manager.get_skill("demo")
        self.assertIsNotNone(skill_before_delete)
        self.assertFalse(skill_before_delete.is_builtin)

        result = await skills_router.delete_skill("demo")

        self.assertEqual(result["deletion_mode"], "user_delete_and_builtin_tombstone")
        self.assertFalse(override_file.exists())
        self.assertTrue(builtin_file.exists())
        self.assertIsNone(skill_manager.get_skill("demo"))


if __name__ == "__main__":
    unittest.main()
