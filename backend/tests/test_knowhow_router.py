import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import knowhow as knowhow_router
from services.storage import storage


class KnowhowRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.original_db_path = storage._db_path

        if storage._db is not None:
            await storage.close()

        storage._db_path = Path(self.temp_dir.name) / "test.db"
        await storage.initialize()
        self.admin = await storage.get_user_by_username("admin")
        self.assertIsNotNone(self.admin)

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        self.temp_dir.cleanup()

    async def test_export_rules_returns_backup_payload(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="需要检查供应商资质",
                weight=3,
                source="user",
            ),
            user=self.admin,
        )

        response = await knowhow_router.export_rules(user=self.admin)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(payload["kind"], "knowhow_rules_export")
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["total_rules"], 1)
        self.assertEqual(payload["rules"][0]["category"], "采购预审")
        self.assertEqual(payload["rules"][0]["rule_text"], "需要检查供应商资质")

    async def test_import_rules_append_skips_duplicates(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="需要检查供应商资质",
                weight=3,
                source="user",
            ),
            user=self.admin,
        )

        result = await knowhow_router.import_rules(
            payload={
                "rules": [
                    {"category": "采购预审", "rule_text": "需要检查供应商资质", "weight": 5},
                    {"category": "合规性", "rule_text": "确认审批链完整", "weight": 2, "is_active": 0},
                ]
            },
            strategy="append",
            user=self.admin,
        )
        listed = await knowhow_router.list_rules(user=self.admin)

        self.assertEqual(result["strategy"], "append")
        self.assertEqual(result["total_in_file"], 2)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["total_after_import"], 2)
        self.assertEqual(len(listed["rules"]), 2)
        imported = next(rule for rule in listed["rules"] if rule["category"] == "合规性")
        self.assertEqual(imported["rule_text"], "确认审批链完整")
        self.assertEqual(imported["is_active"], 0)
        self.assertEqual(imported["source"], "imported")

    async def test_import_rules_replace_clears_existing_rules(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="老规则",
                weight=3,
                source="user",
            ),
            user=self.admin,
        )

        result = await knowhow_router.import_rules(
            payload={
                "rules": [
                    {
                        "category": "技术规格",
                        "rule_text": "规格参数要和招标书一致",
                        "weight": 4,
                        "source": "imported",
                        "is_active": 1,
                    }
                ]
            },
            strategy="replace",
            user=self.admin,
        )
        listed = await knowhow_router.list_rules(user=self.admin)

        self.assertEqual(result["strategy"], "replace")
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["total_after_import"], 1)
        self.assertEqual(len(listed["rules"]), 1)
        self.assertEqual(listed["rules"][0]["category"], "技术规格")
        self.assertEqual(listed["rules"][0]["rule_text"], "规格参数要和招标书一致")

    async def test_create_and_rename_empty_category(self):
        created = await knowhow_router.create_category(
            knowhow_router.CategoryCreateRequest(name="????"),
            user=self.admin,
        )
        self.assertEqual(created["category"]["name"], "????")

        listed = await knowhow_router.list_categories(user=self.admin)
        self.assertIn("????", {item["name"] for item in listed["categories"]})

        renamed = await knowhow_router.rename_category(
            "????",
            knowhow_router.CategoryRenameRequest(new_name="????-????"),
            user=self.admin,
        )
        self.assertEqual(renamed["affected_rules"], 0)

        listed_again = await knowhow_router.list_categories(user=self.admin)
        category_names = {item["name"] for item in listed_again["categories"]}
        self.assertIn("????-????", category_names)
        self.assertNotIn("????", category_names)


if __name__ == "__main__":
    unittest.main()
