import json
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from uuid import uuid4


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from routers import knowhow as knowhow_router
from services.knowhow_service import knowhow_service
from services.storage import storage


class KnowhowRouterApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = Path(BACKEND_ROOT) / ".tmp-knowhow-router-tests" / uuid4().hex
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.original_db_path = storage._db_path

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

    async def test_export_rules_returns_phase2_payload(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                title="Supplier qualification",
                rule_text="Supplier should provide ISO9001 or equivalent qualification evidence.",
                trigger_terms=["supplier qualification", "iso9001"],
                examples=["Does this supplier need ISO9001 evidence?"],
                weight=3,
                source="user",
            ),
            user=self.admin,
        )

        response = await knowhow_router.export_rules(user=self.admin)
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(payload["kind"], "knowhow_rules_export")
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["total_rules"], 1)
        self.assertEqual(payload["rules"][0]["category"], "procurement_review")
        self.assertEqual(payload["rules"][0]["title"], "Supplier qualification")
        self.assertEqual(payload["rules"][0]["trigger_terms"], ["supplier qualification", "iso9001"])

    async def test_import_rules_append_preserves_phase2_fields(self):
        result = await knowhow_router.import_rules(
            payload={
                "rules": [
                    {
                        "category": "contract_review",
                        "title": "Payment term check",
                        "rule_text": "Payment terms must define milestone and acceptance conditions.",
                        "trigger_terms": ["payment terms", "milestone"],
                        "exclude_terms": ["marketing copy"],
                        "applies_when": "Used when the user asks whether contract payment clauses are complete.",
                        "not_applies_when": "Do not use for greetings.",
                        "examples": ["Are these payment terms complete?"],
                        "weight": 4,
                    }
                ]
            },
            strategy="append",
            user=self.admin,
        )
        listed = await knowhow_router.list_rules(user=self.admin)
        imported = listed["rules"][0]

        self.assertEqual(result["strategy"], "append")
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(imported["title"], "Payment term check")
        self.assertEqual(imported["trigger_terms"], ["payment terms", "milestone"])
        self.assertEqual(imported["exclude_terms"], ["marketing copy"])
        self.assertEqual(imported["examples"], ["Are these payment terms complete?"])

    async def test_category_profile_can_be_updated(self):
        await knowhow_router.create_category(
            knowhow_router.CategoryCreateRequest(name="contract_review"),
            user=self.admin,
        )

        updated = await knowhow_router.update_category_profile(
            "contract_review",
            knowhow_router.CategoryUpdateRequest(
                description="Contract clause review and completeness checks.",
                aliases=["legal review", "agreement review"],
                example_queries=["Are these contract payment terms complete?"],
                applies_to="Contracts, payment clauses, breach penalties.",
            ),
            user=self.admin,
        )

        category = updated["category"]
        self.assertEqual(category["name"], "contract_review")
        self.assertEqual(category["description"], "Contract clause review and completeness checks.")
        self.assertEqual(category["aliases"], ["legal review", "agreement review"])
        self.assertEqual(category["example_queries"], ["Are these contract payment terms complete?"])
        self.assertEqual(category["applies_to"], "Contracts, payment clauses, breach penalties.")

    async def test_minimal_rule_input_auto_enriches_hidden_fields(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="contract_review",
                rule_text="Payment terms must define milestone and acceptance conditions.",
                weight=3,
            ),
            user=self.admin,
        )

        payload = await knowhow_router.list_rules(active_only=False, user=self.admin)
        rule = payload["rules"][0]

        self.assertEqual(rule["category"], "contract_review")
        self.assertTrue(rule["title"])
        self.assertTrue(rule["trigger_terms"])
        self.assertTrue(rule["applies_when"])
        self.assertTrue(rule["examples"])
        self.assertTrue(rule["retrieval_summary"])
        self.assertTrue(rule["retrieval_queries"])

    async def test_category_profile_auto_refreshes_after_simple_rule_save(self):
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="supplier_due_diligence",
                rule_text="Supplier should provide ISO9001 qualification and delivery plan evidence.",
                weight=2,
            ),
            user=self.admin,
        )

        payload = await knowhow_router.list_categories(user=self.admin)
        category = next(item for item in payload["categories"] if item["name"] == "supplier_due_diligence")

        self.assertGreater(category["rule_count"], 0)
        self.assertTrue(category["description"])
        self.assertTrue(category["applies_to"])
        self.assertTrue(category["example_queries"])

    async def test_update_rule_regenerates_hidden_metadata_when_content_changes(self):
        created = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Supplier should provide ISO9001 qualification evidence.",
                weight=2,
            ),
            user=self.admin,
        )

        updated = await knowhow_router.update_rule(
            created["id"],
            knowhow_router.KnowhowRuleUpdate(
                rule_text="Payment terms must define milestone acceptance and advance payment ratio.",
            ),
            user=self.admin,
        )

        self.assertEqual(updated["rule_text"], "Payment terms must define milestone acceptance and advance payment ratio.")
        self.assertTrue(updated["title"])
        self.assertIn("payment", " ".join(updated["trigger_terms"]).lower())
        self.assertTrue(updated["examples"])
        self.assertTrue(updated["retrieval_summary"])
        self.assertTrue(updated["retrieval_queries"])

    async def test_default_rules_backfill_category_registry(self):
        added = await knowhow_service.ensure_defaults()
        stats = await knowhow_router.get_stats(user=self.admin)

        self.assertGreaterEqual(added, 0)
        self.assertGreater(stats["total_rules"], 0)
        self.assertTrue(stats["categories"])

    async def test_initialize_migrates_legacy_knowhow_rules_before_owner_group_index_creation(self):
        await storage.close()
        storage._db_path.unlink(missing_ok=True)

        legacy_db = sqlite3.connect(storage._db_path)
        legacy_db.executescript(
            """
            CREATE TABLE workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                icon TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_archived INTEGER DEFAULT 0
            );

            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                system_role TEXT DEFAULT 'user',
                group_id TEXT,
                can_manage_group_knowhow INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT DEFAULT '',
                description TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                agent_prompt TEXT DEFAULT '',
                capabilities TEXT DEFAULT '[]',
                chat_capabilities TEXT DEFAULT '[]',
                agent_preflight TEXT DEFAULT '[]',
                allowed_surfaces TEXT DEFAULT '["chat"]',
                agent_allowed_tools TEXT DEFAULT '[]',
                is_builtin INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE knowhow_rules (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                rule_text TEXT NOT NULL,
                weight INTEGER DEFAULT 2,
                hit_count INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                source TEXT DEFAULT 'user',
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        legacy_db.commit()
        legacy_db.close()

        await storage.initialize()

        columns = await storage._table_columns("knowhow_rules")
        self.assertIn("owner_id", columns)
        self.assertIn("owner_group_id", columns)
        self.assertIn("retrieval_summary", columns)
        self.assertIn("retrieval_queries", columns)


if __name__ == "__main__":
    unittest.main()
