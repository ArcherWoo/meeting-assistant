import os
import sys
import unittest
from types import SimpleNamespace


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.agent_runtime.deps import _apply_skill_profile
from services.agent_runtime.models import RolePolicy
from services.skill_parser import SkillExecutionProfile


class AgentDepsTests(unittest.TestCase):
    def test_apply_skill_profile_intersects_role_tools(self):
        policy = RolePolicy(
            role_id="executor",
            allowed=True,
            capabilities=["rag", "skills"],
            allowed_surfaces=["agent"],
            allowed_tools=["get_skill_definition", "extract_file_text", "query_knowledge", "search_knowhow_rules"],
            enable_rag=True,
            enable_skill_matching=True,
            instructions="test",
            display_name="Executor",
        )
        skill = SimpleNamespace(
            execution_profile=SkillExecutionProfile(
                preferred_role_id="executor",
                allowed_tools=["extract_file_text", "query_knowledge"],
                output_kind="report",
            )
        )

        profile, updated_policy = _apply_skill_profile(policy, skill)

        self.assertEqual(profile.allowed_tools, ["extract_file_text", "query_knowledge"])
        self.assertEqual(updated_policy.allowed_tools, ["extract_file_text", "query_knowledge"])
        self.assertTrue(updated_policy.enable_rag)
        self.assertTrue(updated_policy.enable_skill_matching)


if __name__ == "__main__":
    unittest.main()
