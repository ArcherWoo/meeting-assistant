import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import settings as settings_router
from services.storage import storage


class SettingsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.original_db_path = storage._db_path

        if storage._db is not None:
            await storage.close()

        storage._db_path = Path(self.temp_dir.name) / "test.db"
        await storage.initialize()

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        self.temp_dir.cleanup()

    async def test_update_system_prompts_batch_persists_three_modes(self):
        request = settings_router.SystemPromptBundleRequest(
            prompts={
                "copilot": "Copilot prompt",
                "builder": "Builder prompt",
                "agent": "Agent prompt",
            }
        )

        result = await settings_router.update_system_prompts(request)
        bundle = await settings_router.get_system_prompts()

        self.assertEqual(result["prompts"]["copilot"], "Copilot prompt")
        self.assertEqual(bundle["prompts"]["builder"], "Builder prompt")
        self.assertEqual(bundle["custom_modes"], ["agent", "builder", "copilot"])

    async def test_system_prompt_presets_support_create_list_delete(self):
        request = settings_router.SystemPromptPresetRequest(
            name="Weekly review",
            mode="copilot",
            prompt="Copilot prompt",
        )

        created = await settings_router.create_system_prompt_preset(request)
        listed = await settings_router.list_system_prompt_presets()
        deleted = await settings_router.delete_system_prompt_preset(created["preset"]["id"])
        after_delete = await settings_router.list_system_prompt_presets()

        self.assertEqual(created["preset"]["name"], "Weekly review")
        self.assertEqual(created["preset"]["mode"], "copilot")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["presets"][0]["prompt"], "Copilot prompt")
        self.assertEqual(deleted["id"], created["preset"]["id"])
        self.assertEqual(after_delete["total"], 0)


if __name__ == "__main__":
    unittest.main()
