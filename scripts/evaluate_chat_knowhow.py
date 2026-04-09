from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.context_assembler import ContextAssembler
import services.context_assembler as context_assembler_module
from services.knowhow_router import KnowhowRouter
from services.knowhow_service import knowhow_service
from services.llm_service import llm_service as shared_llm_service
from services.retrieval_planner import RetrievalPlanner, RetrievalPlannerSettings
from services.storage import storage


SEED_RULES: list[dict[str, Any]] = [
    {
        "category": "采购预审",
        "title": "供应商资质要求",
        "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质。",
        "trigger_terms": ["供应商资质", "ISO", "认证", "资格"],
        "examples": ["这个供应商缺少 ISO 认证还能继续吗"],
        "weight": 3,
    },
    {
        "category": "采购预审",
        "title": "价格偏差判断",
        "rule_text": "价格与历史同品类均价对比，偏差应在合理范围内，异常偏差需要补充解释。",
        "trigger_terms": ["价格偏差", "均价", "报价", "偏差说明"],
        "examples": ["这次报价比历史均价高很多是否合理"],
        "weight": 3,
    },
    {
        "category": "采购预审",
        "title": "单一来源合规判断",
        "rule_text": "Single Source 方案需要提供充分理由，并说明是否存在 Multi-Source 替代可能。",
        "trigger_terms": ["single source", "multi-source", "单一来源", "唯一供应商"],
        "examples": ["唯一供应商方案是否需要补充理由"],
        "weight": 4,
    },
    {
        "category": "合同审查",
        "title": "付款条款合理性",
        "rule_text": "付款方式与条件应明确，需要关注预付比例、验收付款、质保金等安排。",
        "trigger_terms": ["付款方式", "预付款", "验收付款", "质保金"],
        "examples": ["30%预付款、70%验收后支付是否合理"],
        "weight": 3,
    },
    {
        "category": "合同审查",
        "title": "交付计划完整性",
        "rule_text": "交付时间节点应明确，并包含里程碑和交付计划。",
        "trigger_terms": ["交付", "里程碑", "交期"],
        "examples": ["交付计划只写了一个月底完成，这样够不够"],
        "weight": 2,
    },
]


@dataclass
class EvalCase:
    id: str
    query: str
    kind: str
    expected_category: str = ""
    expected_title_contains: str = ""
    expected_focus: str = ""
    requires_llm: bool = False
    notes: str = ""


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    skipped: bool
    reason: str
    planner_selected_knowhow: bool
    knowhow_count: int
    is_library_summary: bool
    matched_titles: list[str]
    matched_categories: list[str]
    total_ms: int
    planner_ms: int
    knowhow_ms: int
    llm_calls: int
    llm_ms: int


class CountingLLMService:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.chat_calls = 0
        self.chat_ms_total = 0

    async def chat(self, *args, **kwargs):
        started = time.perf_counter()
        self.chat_calls += 1
        try:
            return await self._inner.chat(*args, **kwargs)
        finally:
            self.chat_ms_total += round((time.perf_counter() - started) * 1000)

    def extract_text_content(self, response):
        return self._inner.extract_text_content(response)


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def load_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in payload]


def build_markdown_report(
    *,
    mode_label: str,
    cases: list[EvalCase],
    results: list[EvalResult],
) -> str:
    executed = [item for item in results if not item.skipped]
    passed = [item for item in executed if item.passed]
    failed = [item for item in executed if not item.passed]
    total_ms = [item.total_ms for item in executed]
    planner_ms = [item.planner_ms for item in executed]
    knowhow_ms = [item.knowhow_ms for item in executed]
    llm_calls = [item.llm_calls for item in executed]

    lines = [
        "# Chat Knowhow 评测报告",
        "",
        f"- 模式：`{mode_label}`",
        f"- 样本数：`{len(cases)}`",
        f"- 实际执行：`{len(executed)}`",
        f"- 通过：`{len(passed)}`",
        f"- 失败：`{len(failed)}`",
        "",
        "## 指标",
        "",
    ]
    if executed:
        lines.extend(
            [
                f"- 通过率：`{round(len(passed) / len(executed) * 100, 1)}%`",
                f"- 平均总耗时：`{round(statistics.mean(total_ms), 2)} ms`",
                f"- P95 总耗时：`{percentile(total_ms, 0.95)} ms`",
                f"- 平均规划耗时：`{round(statistics.mean(planner_ms), 2)} ms`",
                f"- 平均 knowhow 耗时：`{round(statistics.mean(knowhow_ms), 2)} ms`",
                f"- 平均每例 LLM 调用数：`{round(statistics.mean(llm_calls), 2)}`",
                "",
                "## 明细",
                "",
                "| case | result | planner knowhow | knowhow count | total ms | llm calls | reason |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in results:
            status = "skipped" if item.skipped else ("pass" if item.passed else "fail")
            lines.append(
                f"| `{item.case_id}` | `{status}` | `{item.planner_selected_knowhow}` | "
                f"`{item.knowhow_count}` | `{item.total_ms}` | `{item.llm_calls}` | {item.reason or '-'} |"
            )
    if failed:
        lines.extend(["", "## 失败样本", ""])
        for item in failed:
            lines.append(
                f"- `{item.case_id}`: {item.reason}；命中分类={item.matched_categories}；命中标题={item.matched_titles}"
            )
    return "\n".join(lines) + "\n"


async def seed_rules(admin: dict) -> None:
    for rule in SEED_RULES:
        await knowhow_service.add_rule(
            category=rule["category"],
            title=rule["title"],
            rule_text=rule["rule_text"],
            trigger_terms=rule.get("trigger_terms"),
            examples=rule.get("examples"),
            weight=rule.get("weight", 2),
            owner_id=admin["id"],
        )


async def evaluate_case(
    *,
    case: EvalCase,
    assembler: ContextAssembler,
    planner_settings: RetrievalPlannerSettings,
    user: dict,
    counting_llm: CountingLLMService,
    llm_enabled: bool,
) -> EvalResult:
    if case.requires_llm and not llm_enabled:
        return EvalResult(
            case_id=case.id,
            passed=False,
            skipped=True,
            reason="requires_llm",
            planner_selected_knowhow=False,
            knowhow_count=0,
            is_library_summary=False,
            matched_titles=[],
            matched_categories=[],
            total_ms=0,
            planner_ms=0,
            knowhow_ms=0,
            llm_calls=0,
            llm_ms=0,
        )

    llm_calls_before = counting_llm.chat_calls
    llm_ms_before = counting_llm.chat_ms_total

    started_total = time.perf_counter()
    started_planner = time.perf_counter()
    plan = await assembler._plan_retrieval(
        user_query=case.query,
        role_id="copilot",
        planner_settings=planner_settings,
        enabled_surfaces=("knowledge", "knowhow", "skill"),
        trace_handler=None,
    )
    planner_ms = round((time.perf_counter() - started_planner) * 1000)

    started_knowhow = time.perf_counter()
    knowhow_rules = await assembler.get_knowhow_rules(
        case.query,
        limit=5,
        user=user,
        planner_settings=planner_settings,
    )
    knowhow_ms = round((time.perf_counter() - started_knowhow) * 1000)
    total_ms = round((time.perf_counter() - started_total) * 1000)

    llm_calls_after = counting_llm.chat_calls
    llm_ms_after = counting_llm.chat_ms_total
    llm_calls = llm_calls_after - llm_calls_before
    llm_ms = llm_ms_after - llm_ms_before

    planner_selected_knowhow = any(action.surface == "knowhow" for action in plan.actions)
    matched_titles = [str(rule.get("title") or "").strip() for rule in knowhow_rules if str(rule.get("title") or "").strip()]
    matched_categories = [str(rule.get("category") or "").strip() for rule in knowhow_rules if str(rule.get("category") or "").strip()]
    is_library_summary = bool(knowhow_rules and knowhow_rules[0].get("is_virtual"))

    passed = False
    reason = ""
    if case.kind == "skip":
        passed = not knowhow_rules and not planner_selected_knowhow
        reason = "skip_ok" if passed else "unexpected_knowhow_triggered"
    elif case.kind == "library":
        focus = str(knowhow_rules[0].get("title") or "") if knowhow_rules else ""
        expected_focus = case.expected_focus
        if expected_focus == "stats":
            passed = is_library_summary and "统计" in focus
        elif expected_focus == "categories":
            passed = is_library_summary and "分类" in focus
        else:
            passed = is_library_summary
        reason = "library_summary_ok" if passed else "library_summary_missed"
    else:
        title_hit = any(case.expected_title_contains in title for title in matched_titles) if case.expected_title_contains else True
        category_hit = any(case.expected_category == category for category in matched_categories) if case.expected_category else True
        passed = planner_selected_knowhow and bool(knowhow_rules) and title_hit and category_hit
        if not planner_selected_knowhow:
            reason = "planner_did_not_select_knowhow"
        elif not knowhow_rules:
            reason = "no_knowhow_rules_returned"
        elif not title_hit:
            reason = "expected_rule_title_not_found"
        elif not category_hit:
            reason = "expected_category_not_found"
        else:
            reason = "rule_hit_ok"

    return EvalResult(
        case_id=case.id,
        passed=passed,
        skipped=False,
        reason=reason,
        planner_selected_knowhow=planner_selected_knowhow,
        knowhow_count=len(knowhow_rules),
        is_library_summary=is_library_summary,
        matched_titles=matched_titles,
        matched_categories=matched_categories,
        total_ms=total_ms,
        planner_ms=planner_ms,
        knowhow_ms=knowhow_ms,
        llm_calls=llm_calls,
        llm_ms=llm_ms,
    )


async def main_async(args) -> int:
    temp_root = BACKEND_ROOT / ".tmp-knowhow-eval" / uuid4().hex
    temp_root.mkdir(parents=True, exist_ok=True)
    original_db_path = storage._db_path
    original_router = context_assembler_module.knowhow_router

    counting_llm = CountingLLMService(shared_llm_service)
    planner = RetrievalPlanner(llm_service=counting_llm)
    local_router = KnowhowRouter(llm_service=counting_llm)
    context_assembler_module.knowhow_router = local_router
    assembler = ContextAssembler(planner=planner)

    try:
        if storage._db is not None:
            await storage.close()
        storage._db_path = temp_root / "eval.db"
        await storage.initialize()
        admin = await storage.get_user_by_username("admin")
        if not admin:
            raise RuntimeError("未找到默认管理员用户")

        await seed_rules(admin)
        cases = load_cases(Path(args.cases).resolve())
        llm_enabled = bool(args.api_url.strip() and args.api_key.strip())
        planner_settings = RetrievalPlannerSettings(
            api_url=args.api_url,
            api_key=args.api_key,
            model=args.model,
            user_id=str(admin["id"]),
        )

        results = [
            await evaluate_case(
                case=case,
                assembler=assembler,
                planner_settings=planner_settings,
                user=admin,
                counting_llm=counting_llm,
                llm_enabled=llm_enabled,
            )
            for case in cases
        ]

        executed = [item for item in results if not item.skipped]
        passed = [item for item in executed if item.passed]
        failed = [item for item in executed if not item.passed]
        skipped = [item for item in results if item.skipped]
        total_ms = [item.total_ms for item in executed]
        mode_label = "llm" if llm_enabled else "heuristic"

        print("")
        print("Chat Knowhow 评测")
        print(f"模式:              {mode_label}")
        print(f"样本总数:          {len(cases)}")
        print(f"实际执行:          {len(executed)}")
        print(f"跳过样本:          {len(skipped)}")
        print(f"通过样本:          {len(passed)}")
        print(f"失败样本:          {len(failed)}")
        if total_ms:
            print(f"平均总耗时:        {round(statistics.mean(total_ms), 2)} ms")
            print(f"P95 总耗时:        {percentile(total_ms, 0.95)} ms")
        print(f"累计 LLM 调用:     {sum(item.llm_calls for item in executed)}")

        if skipped:
            print("")
            print("跳过样本:")
            for item in skipped:
                print(f"- {item.case_id}: {item.reason}")

        if failed:
            print("")
            print("失败样本:")
            for item in failed:
                print(
                    f"- {item.case_id}: {item.reason}; "
                    f"planner_knowhow={item.planner_selected_knowhow}; "
                    f"matched_titles={item.matched_titles}; matched_categories={item.matched_categories}"
                )

        markdown = build_markdown_report(mode_label=mode_label, cases=cases, results=results)
        if args.markdown_out:
            output_path = Path(args.markdown_out).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8-sig")
            print("")
            print(f"Markdown 报告已写入: {output_path}")

        return 0 if not failed else 1
    finally:
        context_assembler_module.knowhow_router = original_router
        await storage.close()
        storage._db_path = original_db_path
        shutil.rmtree(temp_root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate chat -> knowhow hit quality and latency.")
    parser.add_argument(
        "--cases",
        default=str(REPO_ROOT / "scripts" / "fixtures" / "knowhow-eval-cases.json"),
        help="评测集 JSON 文件路径",
    )
    parser.add_argument("--api-url", default="", help="可选：真实 LLM API URL")
    parser.add_argument("--api-key", default="", help="可选：真实 LLM API Key")
    parser.add_argument("--model", default="gpt-4o", help="可选：真实 LLM 模型名")
    parser.add_argument("--markdown-out", default="", help="可选：评测报告 Markdown 输出路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
