import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers.chat import ChatMessage, ChatRequest, _build_messages
from services.prompt_template_service import prompt_template_service
from services.storage import storage


class PromptTemplateServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_resolve_mode_prompt_merges_base_templates_variables_and_extra_prompt(self):
        template = await prompt_template_service.create_template(
            name="analysis-style",
            description="",
            scope="copilot",
            content="Tone: {{tone}}\nMode: {{mode_label}}\nDate: {{today}}\nMissing: {{missing}}",
            variables={"tone": "neutral"},
        )
        await prompt_template_service.save_mode_config(
            "copilot",
            template_ids=[template["id"]],
            variables={"tone": "executive"},
            extra_prompt="Tail note",
        )

        resolved = await prompt_template_service.resolve_mode_prompt("copilot", "Base prompt")

        self.assertEqual(resolved["template_ids"], [template["id"]])
        self.assertIn("Base prompt", resolved["resolved_prompt"])
        self.assertIn("Tone: executive", resolved["resolved_prompt"])
        self.assertIn("Mode: Copilot", resolved["resolved_prompt"])
        self.assertIn("Date:", resolved["resolved_prompt"])
        self.assertIn("Tail note", resolved["resolved_prompt"])
        self.assertIn("missing", resolved["missing_variables"])

    async def test_build_messages_uses_plain_system_prompt_only(self):
        await storage.set_setting("system_prompt_copilot", "Base system prompt")
        template = await prompt_template_service.create_template(
            name="bullet-style",
            description="",
            scope="global",
            content="Output style: {{style}}",
            variables={"style": "bullet list"},
        )
        await prompt_template_service.save_mode_config(
            "copilot",
            template_ids=[template["id"]],
            variables={},
            extra_prompt="Mention open questions.",
        )

        request = ChatRequest(
            messages=[ChatMessage(role="user", content="帮我总结会议结论")],
            api_key="sk-test",
            mode="copilot",
        )

        messages = await _build_messages(request)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Base system prompt", messages[0]["content"])
        self.assertNotIn("Output style: bullet list", messages[0]["content"])
        self.assertNotIn("Mention open questions.", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")

    async def test_list_templates_includes_builtin_templates(self):
        templates = await prompt_template_service.list_templates("copilot")

        builtin = next((item for item in templates if item["id"].startswith("builtin:executive-brief/")), None)

        self.assertIsNotNone(builtin)
        self.assertTrue(builtin["is_builtin"])
        self.assertEqual(builtin["source"], "builtin")
        self.assertEqual(builtin["pack_id"], "executive-brief")

    async def test_apply_builtin_pack_updates_multiple_modes(self):
        custom = await prompt_template_service.create_template(
            name="audience-template",
            description="",
            scope="copilot",
            content="Audience: {{audience}}",
            variables={"audience": "internal"},
        )
        await prompt_template_service.save_mode_config(
            "copilot",
            template_ids=[custom["id"]],
            variables={"audience": "sales", "unused": "drop"},
            extra_prompt="Keep extra",
        )

        result = await prompt_template_service.apply_builtin_pack(
            "executive-brief",
            ["copilot", "agent"],
            strategy="append",
        )
        pack = await prompt_template_service.get_builtin_pack("executive-brief")
        copilot_ids = [item["id"] for item in pack["templates"] if item["scope"] in {"global", "copilot"}]
        agent_ids = [item["id"] for item in pack["templates"] if item["scope"] in {"global", "agent"}]
        copilot_config = await prompt_template_service.get_mode_config("copilot")
        agent_config = await prompt_template_service.get_mode_config("agent")

        self.assertEqual(result["strategy"], "append")
        self.assertEqual(copilot_config["template_ids"], [custom["id"], *copilot_ids])
        self.assertEqual(agent_config["template_ids"], agent_ids)
        self.assertEqual(copilot_config["variables"], {"audience": "sales"})
        self.assertEqual(copilot_config["extra_prompt"], "Keep extra")


if __name__ == "__main__":
    unittest.main()
