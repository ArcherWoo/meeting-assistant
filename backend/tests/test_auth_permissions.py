import os
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import uuid


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import HTTPException

from routers import auth as auth_router
from routers import conversations as conversations_router
from routers import knowhow as knowhow_router
from routers import settings as settings_router
from routers import skills as skills_router
from services.context_assembler import context_assembler
from services.retrieval_planner import RetrievalPlannerSettings
from services.skill_manager import skill_manager
from services.storage import storage


PRIVATE_SKILL = """# Skill: Private Review
## Description
Review private procurement material
## Trigger
- keyword: "private-review"
## Steps
1. Inspect the document
2. Summarize the risks
"""


class AuthPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_root = Path(BACKEND_ROOT) / ".tmp-test-data" / f"auth-permissions-{uuid.uuid4().hex}"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        root = self.temp_root
        self.backend_skills_dir = root / "backend_skills"
        self.user_skills_dir = root / "user_skills"
        (self.backend_skills_dir / "builtin").mkdir(parents=True, exist_ok=True)
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
        await skill_manager.reload()

        self.original_db_path = storage._db_path
        if storage._db is not None:
            await storage.close()

        storage._db_path = root / "test.db"
        await storage.initialize()
        self.admin = await storage.get_user_by_username("admin")
        self.assertIsNotNone(self.admin)

    async def asyncTearDown(self):
        await storage.close()
        storage._db_path = self.original_db_path
        skill_manager._skills.clear()
        skill_manager._builtin_sources.clear()
        skill_manager._deleted_builtin_ids = set()
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    async def test_grouped_user_can_login_and_use_group_granted_resources(self):
        group = await storage.create_group("team-a", "Team A")
        await auth_router.register(
            auth_router.RegisterRequest(
                username="grouped-user",
                display_name="Grouped User",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )
        user = await storage.get_user_by_username("grouped-user")
        self.assertIsNotNone(user)

        login = await auth_router.login(
            auth_router.LoginRequest(username="grouped-user", password="pw123456")
        )
        self.assertEqual(login["user"]["group_id"], group["id"])

        role = await storage.create_role(
            name="Private Chat Role",
            owner_id=self.admin["id"],
            allowed_surfaces=["chat"],
        )
        await auth_router.set_grant(
            auth_router.SetGrantRequest(
                resource_type="role",
                resource_id=role["id"],
                grant_type="group",
                grantee_id=group["id"],
            ),
            _admin=self.admin,
        )
        visible_roles = await settings_router.list_roles(user=user)
        self.assertIn(role["id"], {item["id"] for item in visible_roles["roles"]})

        saved_skill = await skills_router.save_skill(
            skills_router.SaveSkillRequest(content=PRIVATE_SKILL, filename="private-review"),
            user=self.admin,
        )
        hidden_skills = await skills_router.list_skills(user=user)
        self.assertNotIn(saved_skill["id"], {skill["id"] for skill in hidden_skills["skills"]})

        hidden_matches = await skills_router.match_skill(
            skills_router.MatchRequest(query="private-review", top_k=5),
            user=user,
        )
        self.assertEqual(hidden_matches["total"], 0)

        await auth_router.set_grant(
            auth_router.SetGrantRequest(
                resource_type="skill",
                resource_id=saved_skill["id"],
                grant_type="group",
                grantee_id=group["id"],
            ),
            _admin=self.admin,
        )

        visible_skills = await skills_router.list_skills(user=user)
        self.assertIn(saved_skill["id"], {skill["id"] for skill in visible_skills["skills"]})

        skill_detail = await skills_router.get_skill(saved_skill["id"], user=user)
        self.assertEqual(skill_detail["id"], saved_skill["id"])

        visible_matches = await skills_router.match_skill(
            skills_router.MatchRequest(query="private-review", top_k=5),
            user=user,
        )
        self.assertEqual(visible_matches["total"], 1)
        self.assertEqual(visible_matches["matches"][0]["skill_id"], saved_skill["id"])

        knowhow_result = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="需要检查供应商资质文件是否完整",
                weight=3,
                source="user",
            ),
            user=self.admin,
        )
        await auth_router.set_grant(
            auth_router.SetGrantRequest(
                resource_type="knowhow",
                resource_id=knowhow_result["id"],
                grant_type="group",
                grantee_id=group["id"],
            ),
            _admin=self.admin,
        )

        rules = await knowhow_router.list_rules(
            category="采购预审",
            active_only=False,
            user=user,
        )
        self.assertIn(knowhow_result["id"], {rule["id"] for rule in rules["rules"]})

        created = await conversations_router.create_conversation(
            conversations_router.ConversationCreateRequest(
                role_id=role["id"],
                surface="chat",
                title="Grouped user chat",
            ),
            user=user,
        )
        self.assertEqual(created["conversation"]["roleId"], role["id"])

    async def test_user_owned_knowhow_stays_visible_with_category_filter(self):
        group = await storage.create_group("team-b", "Team B")
        created_user = await auth_router.register(
            auth_router.RegisterRequest(
                username="rule-owner",
                display_name="Rule Owner",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        rule_result = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="法务",
                rule_text="需要确认关键合同条款",
                weight=2,
                source="user",
            ),
            user=created_user,
        )

        rules = await knowhow_router.list_rules(
            category="法务",
            active_only=False,
            user=created_user,
        )
        self.assertIn(rule_result["id"], {rule["id"] for rule in rules["rules"]})

    async def test_non_admin_cannot_manage_shared_knowhow_or_library_level_actions(self):
        group = await storage.create_group("team-c", "Team C")
        created_user = await auth_router.register(
            auth_router.RegisterRequest(
                username="shared-rule-reader",
                display_name="Shared Rule Reader",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        shared_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="需要核对供应商资质和单一来源说明",
                weight=3,
                source="user",
            ),
            user=self.admin,
        )
        await auth_router.set_grant(
            auth_router.SetGrantRequest(
                resource_type="knowhow",
                resource_id=shared_rule["id"],
                grant_type="group",
                grantee_id=group["id"],
            ),
            _admin=self.admin,
        )

        with self.assertRaises(HTTPException) as update_context:
            await knowhow_router.update_rule(
                shared_rule["id"],
                knowhow_router.KnowhowRuleUpdate(rule_text="试图篡改共享规则"),
                user=created_user,
            )
        self.assertEqual(update_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as delete_context:
            await knowhow_router.delete_rule(shared_rule["id"], user=created_user)
        self.assertEqual(delete_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as export_context:
            await knowhow_router.export_rules(user=created_user)
        self.assertEqual(export_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as import_context:
            await knowhow_router.import_rules(
                payload={"rules": []},
                strategy="append",
                user=created_user,
            )
        self.assertEqual(import_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as create_category_context:
            await knowhow_router.create_category(
                knowhow_router.CategoryCreateRequest(name="普通用户新分类"),
                user=created_user,
            )
        self.assertEqual(create_category_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as rename_category_context:
            await knowhow_router.rename_category(
                "采购预审",
                knowhow_router.CategoryRenameRequest(new_name="采购预审-改名"),
                user=created_user,
            )
        self.assertEqual(rename_category_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as delete_category_context:
            await knowhow_router.delete_category("采购预审", delete_rules=True, user=created_user)
        self.assertEqual(delete_category_context.exception.status_code, 403)

    async def test_non_admin_only_sees_categories_with_visible_rules(self):
        group = await storage.create_group("team-d", "Team D")
        created_user = await auth_router.register(
            auth_router.RegisterRequest(
                username="category-viewer",
                display_name="Category Viewer",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        visible_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="采购预审",
                rule_text="共享给小组的规则",
                weight=2,
                source="user",
            ),
            user=self.admin,
        )
        await auth_router.set_grant(
            auth_router.SetGrantRequest(
                resource_type="knowhow",
                resource_id=visible_rule["id"],
                grant_type="group",
                grantee_id=group["id"],
            ),
            _admin=self.admin,
        )

        await knowhow_router.create_category(
            knowhow_router.CategoryCreateRequest(name="机密分类"),
            user=self.admin,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="机密分类",
                rule_text="只有管理员可见的机密规则",
                weight=4,
                source="user",
            ),
            user=self.admin,
        )

        categories = await knowhow_router.list_categories(user=created_user)
        category_names = {item["name"] for item in categories["categories"]}

        self.assertIn("采购预审", category_names)
        self.assertNotIn("机密分类", category_names)

    async def test_group_knowhow_manager_can_manage_group_owned_rules_and_import_export_scope(self):
        group = await storage.create_group("team-e", "Team E")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="group-knowhow-manager",
                display_name="Group Knowhow Manager",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member = await auth_router.register(
            auth_router.RegisterRequest(
                username="group-member",
                display_name="Group Member",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )
        other_group = await storage.create_group("team-f", "Team F")
        other_manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="other-group-manager",
                display_name="Other Group Manager",
                password="pw123456",
                system_role="user",
                group_id=other_group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )

        created_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="team-playbook",
                rule_text="This rule belongs to Team E knowhow.",
                weight=2,
                source="user",
                share_to_group=True,
            ),
            user=manager,
        )
        stored_rule = await storage.get_knowhow_rule(created_rule["id"])
        self.assertIsNotNone(stored_rule)
        self.assertEqual(stored_rule["owner_group_id"], group["id"])

        visible_for_member = await knowhow_router.list_rules(
            category="team-playbook",
            active_only=False,
            user=member,
        )
        self.assertIn(created_rule["id"], {rule["id"] for rule in visible_for_member["rules"]})

        with self.assertRaises(HTTPException) as member_update_context:
            await knowhow_router.update_rule(
                created_rule["id"],
                knowhow_router.KnowhowRuleUpdate(rule_text="member should not update this"),
                user=member,
            )
        self.assertEqual(member_update_context.exception.status_code, 403)

        updated_rule = await knowhow_router.update_rule(
            created_rule["id"],
            knowhow_router.KnowhowRuleUpdate(rule_text="Updated by the group knowhow manager"),
            user=manager,
        )
        self.assertEqual(updated_rule["rule_text"], "Updated by the group knowhow manager")

        with self.assertRaises(HTTPException) as other_group_context:
            await knowhow_router.update_rule(
                created_rule["id"],
                knowhow_router.KnowhowRuleUpdate(rule_text="other group must not edit"),
                user=other_manager,
            )
        self.assertEqual(other_group_context.exception.status_code, 403)

        export_response = await knowhow_router.export_rules(user=manager)
        export_payload = json.loads(export_response.body.decode("utf-8"))
        self.assertEqual(export_payload["total_rules"], 1)
        self.assertEqual(export_payload["rules"][0]["owner_group_id"], group["id"])

        import_result = await knowhow_router.import_rules(
            payload={
                "rules": [
                    {
                        "category": "team-playbook",
                        "rule_text": "Imported by group manager",
                        "weight": 3,
                        "owner_id": self.admin["id"],
                        "owner_group_id": other_group["id"],
                    }
                ]
            },
            strategy="append",
            user=manager,
        )
        self.assertEqual(import_result["imported_count"], 1)

        imported_rules = await knowhow_router.list_rules(
            category="team-playbook",
            active_only=False,
            user=member,
        )
        imported_rule = next(
            rule for rule in imported_rules["rules"]
            if rule["rule_text"] == "Imported by group manager"
        )
        self.assertEqual(imported_rule["owner_group_id"], group["id"])
        self.assertEqual(imported_rule["owner_id"], manager["id"])

        with self.assertRaises(HTTPException) as replace_import_context:
            await knowhow_router.import_rules(
                payload={"rules": []},
                strategy="replace",
                user=manager,
            )
        self.assertEqual(replace_import_context.exception.status_code, 403)

    async def test_group_manager_can_choose_private_or_group_shared_rules(self):
        group = await storage.create_group("team-g", "Team G")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="group-rule-author",
                display_name="Group Rule Author",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member = await auth_router.register(
            auth_router.RegisterRequest(
                username="group-rule-reader",
                display_name="Group Rule Reader",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        private_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="team-g-playbook",
                rule_text="Private rule for the manager only",
                weight=2,
                source="user",
                share_to_group=False,
            ),
            user=manager,
        )
        shared_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="team-g-playbook",
                rule_text="Shared baseline for Team G",
                weight=3,
                source="user",
                share_to_group=True,
            ),
            user=manager,
        )

        member_rules = await knowhow_router.list_rules(
            category="team-g-playbook",
            active_only=False,
            user=member,
        )
        member_rule_ids = {rule["id"] for rule in member_rules["rules"]}
        self.assertIn(shared_rule["id"], member_rule_ids)
        self.assertNotIn(private_rule["id"], member_rule_ids)

    async def test_group_rule_management_is_revoked_after_manager_loses_group_permission(self):
        group = await storage.create_group("team-h", "Team H")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="former-group-manager",
                display_name="Former Group Manager",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )

        created_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="team-h-playbook",
                rule_text="Shared rule that should lose manager access later",
                weight=2,
                source="user",
                share_to_group=True,
            ),
            user=manager,
        )

        updated_manager = await auth_router.update_user(
            manager["id"],
            auth_router.UpdateUserRequest(group_id="", can_manage_group_knowhow=False),
            _admin=self.admin,
        )

        with self.assertRaises(HTTPException) as update_context:
            await knowhow_router.update_rule(
                created_rule["id"],
                knowhow_router.KnowhowRuleUpdate(rule_text="former manager must not update"),
                user=updated_manager,
            )
        self.assertEqual(update_context.exception.status_code, 403)

        with self.assertRaises(HTTPException) as delete_context:
            await knowhow_router.delete_rule(created_rule["id"], user=updated_manager)
        self.assertEqual(delete_context.exception.status_code, 403)

        visible_rules = await knowhow_router.list_rules(
            category="team-h-playbook",
            active_only=False,
            user=updated_manager,
        )
        self.assertEqual(visible_rules["total"], 0)

    async def test_group_manager_category_operations_only_affect_group_rules(self):
        group = await storage.create_group("team-i", "Team I")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="category-manager",
                display_name="Category Manager",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member = await auth_router.register(
            auth_router.RegisterRequest(
                username="category-member",
                display_name="Category Member",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="shared-category",
                rule_text="Admin private rule should stay untouched",
                weight=1,
                source="user",
            ),
            user=self.admin,
        )
        group_rule = await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="shared-category",
                rule_text="Group shared rule",
                weight=2,
                source="user",
                share_to_group=True,
            ),
            user=manager,
        )

        rename_result = await knowhow_router.rename_category(
            "shared-category",
            knowhow_router.CategoryRenameRequest(new_name="team-i-category"),
            user=manager,
        )
        self.assertEqual(rename_result["affected_rules"], 1)

        member_rules = await knowhow_router.list_rules(
            category="team-i-category",
            active_only=False,
            user=member,
        )
        self.assertIn(group_rule["id"], {rule["id"] for rule in member_rules["rules"]})

        admin_old_category_rules = await knowhow_router.list_rules(
            category="shared-category",
            active_only=False,
            user=self.admin,
        )
        self.assertEqual(len(admin_old_category_rules["rules"]), 1)
        self.assertEqual(admin_old_category_rules["rules"][0]["rule_text"], "Admin private rule should stay untouched")

    async def test_group_manager_import_deduplicates_within_group_scope_only(self):
        group = await storage.create_group("team-j", "Team J")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="import-scope-manager",
                display_name="Import Scope Manager",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member = await auth_router.register(
            auth_router.RegisterRequest(
                username="import-scope-member",
                display_name="Import Scope Member",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="scope-playbook",
                rule_text="Duplicate text across different scopes",
                weight=2,
                source="user",
            ),
            user=self.admin,
        )

        import_result = await knowhow_router.import_rules(
            payload={
                "rules": [
                    {
                        "category": "scope-playbook",
                        "rule_text": "Duplicate text across different scopes",
                        "weight": 3,
                    }
                ]
            },
            strategy="append",
            user=manager,
        )
        self.assertEqual(import_result["imported_count"], 1)

        member_rules = await knowhow_router.list_rules(
            category="scope-playbook",
            active_only=False,
            user=member,
        )
        self.assertEqual(len(member_rules["rules"]), 1)
        self.assertEqual(member_rules["rules"][0]["owner_group_id"], group["id"])

    async def test_chat_knowhow_context_respects_group_user_visibility(self):
        group_a = await storage.create_group("team-k", "Team K")
        group_b = await storage.create_group("team-l", "Team L")
        manager_a = await auth_router.register(
            auth_router.RegisterRequest(
                username="chat-manager-a",
                display_name="Chat Manager A",
                password="pw123456",
                system_role="user",
                group_id=group_a["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member_a = await auth_router.register(
            auth_router.RegisterRequest(
                username="chat-member-a",
                display_name="Chat Member A",
                password="pw123456",
                system_role="user",
                group_id=group_a["id"],
            ),
            _admin=self.admin,
        )
        manager_b = await auth_router.register(
            auth_router.RegisterRequest(
                username="chat-manager-b",
                display_name="Chat Manager B",
                password="pw123456",
                system_role="user",
                group_id=group_b["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        user_b = await auth_router.register(
            auth_router.RegisterRequest(
                username="chat-user-b",
                display_name="Chat User B",
                password="pw123456",
                system_role="user",
                group_id=group_b["id"],
            ),
            _admin=self.admin,
        )

        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Group A shared rule: supplier qualification documents must be complete",
                weight=3,
                source="user",
                share_to_group=True,
            ),
            user=manager_a,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Personal rule: payment terms must include milestone acceptance",
                weight=2,
                source="user",
            ),
            user=member_a,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Group B shared rule: NDA and data boundary must be explicit",
                weight=3,
                source="user",
                share_to_group=True,
            ),
            user=manager_b,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Other user private rule only for self",
                weight=1,
                source="user",
            ),
            user=user_b,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Admin private rule for admin only",
                weight=4,
                source="user",
            ),
            user=self.admin,
        )

        settings = RetrievalPlannerSettings(api_url="", api_key="", model="deepseek-chat")
        visible_rules = await context_assembler.get_knowhow_rules(
            "What should I review about supplier qualification documents and milestone payment terms?",
            limit=10,
            user=member_a,
            planner_settings=settings,
        )
        visible_texts = {rule["rule_text"] for rule in visible_rules}

        self.assertEqual(
            visible_texts,
            {
                "Group A shared rule: supplier qualification documents must be complete",
                "Personal rule: payment terms must include milestone acceptance",
            },
        )

    async def test_chat_knowhow_library_summary_uses_visible_scope(self):
        group = await storage.create_group("team-m", "Team M")
        manager = await auth_router.register(
            auth_router.RegisterRequest(
                username="summary-manager",
                display_name="Summary Manager",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
                can_manage_group_knowhow=True,
            ),
            _admin=self.admin,
        )
        member = await auth_router.register(
            auth_router.RegisterRequest(
                username="summary-member",
                display_name="Summary Member",
                password="pw123456",
                system_role="user",
                group_id=group["id"],
            ),
            _admin=self.admin,
        )

        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Group shared procurement rule",
                weight=2,
                source="user",
                share_to_group=True,
            ),
            user=manager,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Member private procurement rule",
                weight=2,
                source="user",
            ),
            user=member,
        )
        await knowhow_router.add_rule(
            knowhow_router.KnowhowRuleCreate(
                category="procurement_review",
                rule_text="Admin private procurement rule",
                weight=2,
                source="user",
            ),
            user=self.admin,
        )

        settings = RetrievalPlannerSettings(api_url="", api_key="", model="deepseek-chat")
        member_summary = await context_assembler.get_knowhow_rules(
            "How many knowhow rules are available right now?",
            limit=10,
            user=member,
            planner_settings=settings,
        )
        admin_summary = await context_assembler.get_knowhow_rules(
            "How many knowhow rules are available right now?",
            limit=10,
            user=self.admin,
            planner_settings=settings,
        )

        self.assertEqual(len(member_summary), 1)
        self.assertIn("共 2 条", member_summary[0]["rule_text"])
        self.assertEqual(len(admin_summary), 1)
        self.assertIn("共 3 条", admin_summary[0]["rule_text"])

    async def test_invalid_access_grant_payload_returns_400(self):
        with self.assertRaises(HTTPException) as context:
            await auth_router.set_grant(
                auth_router.SetGrantRequest(
                    resource_type="skill",
                    resource_id="missing-skill",
                    grant_type="user",
                    grantee_id=None,
                ),
                _admin=self.admin,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("grantee_id", str(context.exception.detail))

    async def test_default_admin_cannot_be_downgraded_but_other_admin_can(self):
        delegated_admin = await auth_router.register(
            auth_router.RegisterRequest(
                username="delegated-admin",
                display_name="Delegated Admin",
                password="pw123456",
                system_role="admin",
            ),
            _admin=self.admin,
        )

        updated_user = await auth_router.update_user(
            delegated_admin["id"],
            auth_router.UpdateUserRequest(system_role="user"),
            _admin=self.admin,
        )
        self.assertEqual(updated_user["system_role"], "user")

        reloaded_user = await storage.get_user_by_username("delegated-admin")
        self.assertIsNotNone(reloaded_user)
        self.assertEqual(reloaded_user["system_role"], "user")

        with self.assertRaises(HTTPException) as context:
            await auth_router.update_user(
                self.admin["id"],
                auth_router.UpdateUserRequest(system_role="user"),
                _admin=self.admin,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("admin", str(context.exception.detail))

    async def test_default_admin_cannot_be_deleted_but_other_admin_can(self):
        removable_admin = await auth_router.register(
            auth_router.RegisterRequest(
                username="removable-admin",
                display_name="Removable Admin",
                password="pw123456",
                system_role="admin",
            ),
            _admin=self.admin,
        )

        result = await auth_router.delete_user(removable_admin["id"], admin=self.admin)
        self.assertEqual(result, {"ok": True})
        self.assertIsNone(await storage.get_user_by_username("removable-admin"))

        with self.assertRaises(HTTPException) as context:
            await auth_router.delete_user(self.admin["id"], admin=self.admin)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("admin", str(context.exception.detail))

    async def test_group_can_be_updated(self):
        group = await auth_router.create_group(
            auth_router.CreateGroupRequest(name="team-c", description="Team C"),
            _admin=self.admin,
        )

        updated_group = await auth_router.update_group(
            group["id"],
            auth_router.UpdateGroupRequest(name="team-c-updated", description="Updated Team C"),
            _admin=self.admin,
        )

        self.assertEqual(updated_group["id"], group["id"])
        self.assertEqual(updated_group["name"], "team-c-updated")
        self.assertEqual(updated_group["description"], "Updated Team C")

        stored_group = await storage.get_group_by_id(group["id"])
        self.assertIsNotNone(stored_group)
        self.assertEqual(stored_group["name"], "team-c-updated")
        self.assertEqual(stored_group["description"], "Updated Team C")


if __name__ == "__main__":
    unittest.main()
