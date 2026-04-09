import os
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from services.knowhow_router import KnowhowRouter
from services.retrieval_planner import RetrievalPlannerSettings


class KnowhowRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.rules = [
            {
                "id": "rule-proc-1",
                "category": "procurement_review",
                "title": "Supplier qualification",
                "rule_text": "Supplier should provide ISO9001 or equivalent qualification evidence.",
                "trigger_terms": ["supplier qualification", "iso9001", "certification"],
                "weight": 3,
                "hit_count": 2,
            },
            {
                "id": "rule-proc-2",
                "category": "procurement_review",
                "title": "Single-source rationale",
                "rule_text": "Single-source procurement requires clear risk rationale and approval basis.",
                "trigger_terms": ["single source", "risk rationale", "approval basis"],
                "weight": 4,
                "hit_count": 3,
            },
            {
                "id": "rule-contract-1",
                "category": "contract_review",
                "title": "Payment and penalty clauses",
                "rule_text": "Payment terms, breach liability, and delivery milestones must be explicit in the contract.",
                "trigger_terms": ["payment terms", "breach liability", "delivery milestone"],
                "weight": 2,
                "hit_count": 40,
            },
        ]
        self.category_profiles = [
            {
                "name": "procurement_review",
                "description": "Procurement compliance, supplier access, and single-source risk checks.",
                "aliases": ["purchasing review", "supplier review"],
                "example_queries": ["Is this single-source rationale sufficient?"],
                "applies_to": "Procurement requests and supplier selection.",
            },
            {
                "name": "contract_review",
                "description": "Contract clause completeness and payment term review.",
                "aliases": ["legal review", "agreement review"],
                "example_queries": ["Are these payment clauses complete?"],
                "applies_to": "Contracts, payment clauses, penalty clauses.",
            },
        ]

    async def test_small_talk_skips_knowhow_routing(self):
        router = KnowhowRouter()

        decision, candidate_categories = await router.route(
            "hello",
            self.rules,
            category_profiles=self.category_profiles,
        )

        self.assertFalse(decision.should_retrieve)
        self.assertEqual(decision.strategy, "heuristic_skip")
        self.assertIn("skip_small_talk", decision.notes)
        self.assertIsInstance(candidate_categories, list)

    async def test_retrieve_rules_prefers_matching_category_and_filters_noise(self):
        router = KnowhowRouter()

        result = await router.retrieve_rules(
            "Does this supplier have the required ISO9001 qualification and single-source risk rationale?",
            self.rules,
            category_profiles=self.category_profiles,
            limit=4,
        )

        self.assertTrue(result.decision.should_retrieve)
        self.assertIn("procurement_review", result.decision.categories)
        self.assertGreaterEqual(len(result.rules), 1)
        self.assertEqual(result.rules[0]["category"], "procurement_review")
        self.assertNotEqual(result.rules[0]["id"], "rule-contract-1")

    async def test_category_profiles_help_route_ambiguous_query(self):
        router = KnowhowRouter()

        decision, candidate_categories = await router.route(
            "Are these payment clauses complete enough?",
            self.rules,
            category_profiles=self.category_profiles,
        )

        self.assertTrue(decision.should_retrieve)
        self.assertIn("contract_review", candidate_categories)

    async def test_llm_route_uses_category_profiles_when_configured(self):
        llm_service = AsyncMock()
        llm_service.chat.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"use_knowhow": true, "categories": ["contract_review"], '
                            '"confidence": "medium", "rationale": "contract clause intent"}'
                        )
                    }
                }
            ]
        }
        llm_service.extract_text_content = Mock(
            return_value=(
                '{"use_knowhow": true, "categories": ["contract_review"], '
                '"confidence": "medium", "rationale": "contract clause intent"}'
            )
        )
        router = KnowhowRouter(llm_service=llm_service)

        with patch.object(router, "_hard_skip_gate", return_value=None):
            with patch.object(router, "_heuristic_gate", return_value=None):
                decision, _ = await router.route(
                    "What else should we add to these payment clauses before approval?",
                    self.rules,
                    category_profiles=self.category_profiles,
                    settings=RetrievalPlannerSettings(
                        api_url="https://example.com/v1",
                        api_key="sk-test",
                        model="deepseek-chat",
                    ),
                )

        llm_service.chat.assert_awaited_once()
        self.assertTrue(decision.should_retrieve)
        self.assertEqual(decision.strategy, "llm_route")
        self.assertEqual(decision.categories, ("contract_review",))

    async def test_high_confidence_heuristic_route_skips_llm(self):
        llm_service = AsyncMock()
        llm_service.extract_text_content = Mock(return_value="")
        router = KnowhowRouter(llm_service=llm_service)

        decision, _ = await router.route(
            "Does this supplier have the required ISO9001 qualification and certification?",
            self.rules,
            category_profiles=self.category_profiles,
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
        )

        self.assertTrue(decision.should_retrieve)
        self.assertIn(decision.strategy, {"heuristic_route", "heuristic_category_match", "heuristic_rule_match"})
        llm_service.chat.assert_not_awaited()

    async def test_llm_rule_judge_prunes_candidates(self):
        llm_service = AsyncMock()
        llm_service.chat.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"use_knowhow": true, "categories": ["procurement_review"], '
                                '"confidence": "medium", "rationale": "procurement risk intent"}'
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"selected_ids": ["rule-proc-2"], "rationale": "single-source focus"}'
                        }
                    }
                ]
            },
        ]
        llm_service.extract_text_content = Mock(
            side_effect=[
                '{"use_knowhow": true, "categories": ["procurement_review"], "confidence": "medium", "rationale": "procurement risk intent"}',
                '{"selected_ids": ["rule-proc-2"], "rationale": "single-source focus"}',
            ]
        )
        router = KnowhowRouter(llm_service=llm_service)

        with patch.object(router, "_hard_skip_gate", return_value=None):
            with patch.object(router, "_heuristic_gate", return_value=None):
                with patch.object(router, "_should_use_llm_rule_judge", return_value=True):
                    result = await router.retrieve_rules(
                        "Is the single-source risk rationale sufficient?",
                        self.rules,
                        category_profiles=self.category_profiles,
                        limit=2,
                        settings=RetrievalPlannerSettings(
                            api_url="https://example.com/v1",
                            api_key="sk-test",
                            model="deepseek-chat",
                        ),
                    )

        self.assertEqual([rule["id"] for rule in result.rules], ["rule-proc-2"])
        self.assertEqual(llm_service.chat.await_count, 2)

    async def test_llm_rewritten_query_improves_rule_match(self):
        llm_service = AsyncMock()
        llm_service.chat.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"use_knowhow": true, "categories": ["procurement_review"], '
                            '"confidence": "medium", "rewritten_query": "supplier qualification certification", '
                            '"rationale": "supplier access review"}'
                        )
                    }
                }
            ]
        }
        llm_service.extract_text_content = Mock(
            return_value=(
                '{"use_knowhow": true, "categories": ["procurement_review"], '
                '"confidence": "medium", "rewritten_query": "supplier qualification certification", '
                '"rationale": "supplier access review"}'
            )
        )
        router = KnowhowRouter(llm_service=llm_service)

        result = await router.retrieve_rules(
            "Are the vendor credentials sufficient for onboarding?",
            self.rules,
            category_profiles=self.category_profiles,
            limit=2,
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
        )

        self.assertTrue(result.rules)
        self.assertEqual(result.rules[0]["id"], "rule-proc-1")
        self.assertEqual(result.rules[0].get("route_rewritten_query"), "supplier qualification certification")

    async def test_llm_rule_judge_can_return_no_matching_rules(self):
        llm_service = AsyncMock()
        llm_service.chat.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"use_knowhow": true, "categories": ["procurement_review"], '
                                '"confidence": "medium", "rationale": "procurement risk intent"}'
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"selected_ids": [], "rationale": "no rule is specific enough"}'
                        }
                    }
                ]
            },
        ]
        llm_service.extract_text_content = Mock(
            side_effect=[
                '{"use_knowhow": true, "categories": ["procurement_review"], "confidence": "medium", "rationale": "procurement risk intent"}',
                '{"selected_ids": [], "rationale": "no rule is specific enough"}',
            ]
        )
        router = KnowhowRouter(llm_service=llm_service)

        with patch.object(router, "_hard_skip_gate", return_value=None):
            with patch.object(router, "_heuristic_gate", return_value=None):
                with patch.object(router, "_should_use_llm_rule_judge", return_value=True):
                    result = await router.retrieve_rules(
                        "Please just say hello and do not apply any procurement rule.",
                        self.rules,
                        category_profiles=self.category_profiles,
                        limit=2,
                        settings=RetrievalPlannerSettings(
                            api_url="https://example.com/v1",
                            api_key="sk-test",
                            model="deepseek-chat",
                        ),
                    )

        self.assertEqual(list(result.rules), [])
        self.assertEqual(llm_service.chat.await_count, 2)

    async def test_library_query_detection_prefers_summary_mode(self):
        router = KnowhowRouter()

        decision = await router.inspect_library_query(
            "Knowhow 规则库现在一共有几条规则？",
            category_profiles=self.category_profiles,
        )

        self.assertTrue(decision.use_summary)
        self.assertEqual(decision.focus, "stats")

    async def test_non_library_query_does_not_call_llm_library_detector(self):
        llm_service = AsyncMock()
        llm_service.extract_text_content = Mock(return_value="")
        router = KnowhowRouter(llm_service=llm_service)

        decision = await router.inspect_library_query(
            "Is this single-source rationale sufficient?",
            category_profiles=self.category_profiles,
            settings=RetrievalPlannerSettings(
                api_url="https://example.com/v1",
                api_key="sk-test",
                model="deepseek-chat",
            ),
        )

        self.assertFalse(decision.use_summary)
        llm_service.chat.assert_not_awaited()

    async def test_retrieve_rules_uses_short_ttl_cache_for_repeated_query(self):
        llm_service = AsyncMock()
        llm_service.chat.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"use_knowhow": true, "categories": ["procurement_review"], '
                                '"confidence": "medium", "rationale": "procurement risk intent"}'
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"selected_ids": ["rule-proc-2"], "rationale": "single-source focus"}'
                        }
                    }
                ]
            },
        ]
        llm_service.extract_text_content = Mock(
            side_effect=[
                '{"use_knowhow": true, "categories": ["procurement_review"], "confidence": "medium", "rationale": "procurement risk intent"}',
                '{"selected_ids": ["rule-proc-2"], "rationale": "single-source focus"}',
            ]
        )
        router = KnowhowRouter(llm_service=llm_service)

        with patch.object(router, "_hard_skip_gate", return_value=None):
            with patch.object(router, "_heuristic_gate", return_value=None):
                with patch.object(router, "_should_use_llm_rule_judge", return_value=True):
                    first = await router.retrieve_rules(
                        "Is the single-source risk rationale sufficient?",
                        self.rules,
                        category_profiles=self.category_profiles,
                        limit=2,
                        settings=RetrievalPlannerSettings(
                            api_url="https://example.com/v1",
                            api_key="sk-test",
                            model="deepseek-chat",
                        ),
                    )
                    second = await router.retrieve_rules(
                        "Is the single-source risk rationale sufficient?",
                        self.rules,
                        category_profiles=self.category_profiles,
                        limit=2,
                        settings=RetrievalPlannerSettings(
                            api_url="https://example.com/v1",
                            api_key="sk-test",
                            model="deepseek-chat",
                        ),
                    )

        self.assertEqual([rule["id"] for rule in first.rules], ["rule-proc-2"])
        self.assertEqual([rule["id"] for rule in second.rules], ["rule-proc-2"])
        self.assertEqual(llm_service.chat.await_count, 2)


if __name__ == "__main__":
    unittest.main()
