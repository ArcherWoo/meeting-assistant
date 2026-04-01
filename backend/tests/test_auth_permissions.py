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

from fastapi import HTTPException

from routers import auth as auth_router
from routers import conversations as conversations_router
from routers import knowhow as knowhow_router
from routers import settings as settings_router
from routers import skills as skills_router
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
