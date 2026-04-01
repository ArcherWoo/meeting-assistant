import os
import shutil
import sys
import unittest
from pathlib import Path
import uuid
from fastapi import HTTPException


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import settings as settings_router
from services.storage import storage
from services.system_prompt_defaults import DEFAULT_SYSTEM_PROMPTS


class SettingsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_db_path = storage._db_path
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-test-data" / f"settings-router-{uuid.uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        if storage._db is not None:
            await storage.close()

        storage._db_path = self.temp_dir / "test.db"
        await storage.initialize()
        self.admin = await storage.get_user_by_username("admin")
        self.assertIsNotNone(self.admin)

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_update_system_prompts_batch_persists_three_modes(self):
        request = settings_router.SystemPromptBundleRequest(
            prompts={
                "copilot": "Copilot prompt",
                "builder": "Builder prompt",
                "executor": "Executor prompt",
            }
        )

        result = await settings_router.update_system_prompts(request)
        bundle = await settings_router.get_system_prompts()

        self.assertEqual(result["prompts"]["copilot"], "Copilot prompt")
        self.assertEqual(bundle["prompts"]["builder"], "Builder prompt")
        self.assertEqual(bundle["custom_role_ids"], ["builder", "copilot", "executor"])

    async def test_system_prompt_presets_support_create_list_delete(self):
        request = settings_router.SystemPromptPresetRequest(
            name="Weekly review",
            role_id="copilot",
            prompt="Copilot prompt",
        )

        created = await settings_router.create_system_prompt_preset(request)
        listed = await settings_router.list_system_prompt_presets()
        deleted = await settings_router.delete_system_prompt_preset(created["preset"]["id"])
        after_delete = await settings_router.list_system_prompt_presets()

        self.assertEqual(created["preset"]["name"], "Weekly review")
        self.assertEqual(created["preset"]["role_id"], "copilot")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["presets"][0]["prompt"], "Copilot prompt")
        self.assertEqual(deleted["id"], created["preset"]["id"])
        self.assertEqual(after_delete["total"], 0)

    async def test_reset_system_prompt_returns_builtin_default_even_after_role_edit(self):
        await storage.update_role("copilot", system_prompt="Temporary custom copilot prompt")
        await storage.set_setting("system_prompt_copilot", "Override prompt")

        result = await settings_router.reset_system_prompt("copilot")

        self.assertEqual(result["default_prompt"], DEFAULT_SYSTEM_PROMPTS["copilot"])
        self.assertEqual(result["resolved_prompt"], "Temporary custom copilot prompt")
        self.assertEqual(await storage.get_setting("system_prompt_copilot", default=""), "")

    async def test_default_roles_are_flagged_builtin_but_still_deletable(self):
        roles = await settings_router.list_roles(user=self.admin)
        indexed = {role["id"]: role for role in roles["roles"]}

        self.assertEqual(indexed["copilot"]["is_builtin"], 1)
        self.assertEqual(indexed["builder"]["is_builtin"], 1)
        self.assertEqual(indexed["executor"]["is_builtin"], 1)

        deleted = await settings_router.delete_role("executor", user=self.admin)
        self.assertEqual(deleted["id"], "executor")

        roles_after_delete = await settings_router.list_roles(user=self.admin)
        remaining_ids = {role["id"] for role in roles_after_delete["roles"]}
        self.assertNotIn("executor", remaining_ids)

    async def test_role_crud_roundtrip_persists_agent_policy_fields(self):
        created = await settings_router.create_role(
            settings_router.RoleCreateRequest(
                name="Research Agent",
                icon="🤖",
                description="Handles research tasks",
                system_prompt="Base prompt",
                agent_prompt="Agent-only prompt",
                capabilities=["rag"],
                chat_capabilities=["auto_knowledge"],
                agent_preflight=["auto_knowledge", "pre_match_skill"],
                allowed_surfaces=["chat", "agent"],
                agent_allowed_tools=["query_knowledge", "search_knowhow_rules"],
            ),
            user=self.admin,
        )

        self.assertEqual(created["role"]["agent_prompt"], "Agent-only prompt")
        self.assertEqual(created["role"]["chat_capabilities"], ["auto_knowledge"])
        self.assertEqual(created["role"]["agent_preflight"], ["auto_knowledge", "pre_match_skill"])
        self.assertEqual(created["role"]["allowed_surfaces"], ["chat", "agent"])
        self.assertEqual(created["role"]["agent_allowed_tools"], ["query_knowledge", "search_knowhow_rules"])

        updated = await settings_router.update_role(
            created["role"]["id"],
            settings_router.RoleUpdateRequest(
                chat_capabilities=["auto_knowledge", "auto_skill_suggestion"],
                agent_preflight=["auto_knowledge"],
                allowed_surfaces=["agent"],
                agent_allowed_tools=[],
                agent_prompt="Generic agent prompt",
            ),
            user=self.admin,
        )

        self.assertEqual(updated["role"]["chat_capabilities"], ["auto_knowledge", "auto_skill_suggestion"])
        self.assertEqual(updated["role"]["agent_preflight"], ["auto_knowledge"])
        self.assertEqual(updated["role"]["allowed_surfaces"], ["agent"])
        self.assertEqual(updated["role"]["agent_allowed_tools"], [])
        self.assertEqual(updated["role"]["agent_prompt"], "Generic agent prompt")
        self.assertEqual(updated["role"]["capabilities"], ["rag", "skills"])

    async def test_llm_profiles_are_persisted_and_sanitized_on_read(self):
        created = await settings_router.create_llm_profile(
            settings_router.LLMProfileUpsertRequest(
                name="Server OpenAI",
                api_url="https://api.openai.com/v1",
                api_key="sk-test-secret",
                model="gpt-4o",
                temperature=0.3,
                max_tokens=2048,
                stream=True,
                available_models=["gpt-4o", "gpt-4.1"],
            ),
            user=self.admin,
        )

        await settings_router.set_active_llm_profile(
            settings_router.LLMProfileSelectionRequest(profile_id=created["profile"]["id"]),
            user=self.admin,
        )

        listed = await settings_router.list_llm_profiles_route(user=self.admin)

        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["active_profile_id"], created["profile"]["id"])
        self.assertEqual(listed["profiles"][0]["name"], "Server OpenAI")
        self.assertEqual(listed["profiles"][0]["api_key"], "")
        self.assertTrue(listed["profiles"][0]["has_api_key"])
        self.assertEqual(listed["profiles"][0]["available_models"], ["gpt-4o", "gpt-4.1"])

    async def test_non_admin_cannot_modify_llm_profiles(self):
        user = await storage.create_user(
            username="normal-user",
            display_name="Normal User",
            password_hash="hash",
            system_role="user",
        )

        with self.assertRaises(HTTPException) as context:
            await settings_router.create_llm_profile(
                settings_router.LLMProfileUpsertRequest(
                    name="Blocked",
                    api_url="https://api.openai.com/v1",
                    api_key="sk-test",
                    model="gpt-4o",
                ),
                user=user,
            )

        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
