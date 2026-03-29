from __future__ import annotations

from pydantic_ai import RunContext

from services.agent_runtime.models import (
    AgentCitation,
    AgentDeps,
    AgentToolCallRecord,
    SearchKnowhowRulesInput,
    SearchKnowhowRulesOutput,
)
from services.storage import utc_now_iso


def register_knowhow_tools(agent, policy) -> None:
    if "search_knowhow_rules" not in policy.allowed_tools:
        return

    @agent.tool
    async def search_knowhow_rules(
        ctx: RunContext[AgentDeps],
        input_data: SearchKnowhowRulesInput,
    ) -> SearchKnowhowRulesOutput:
        started_at = utc_now_iso()
        step_index = await ctx.deps.event_adapter.on_tool_start(
            "search_knowhow_rules",
            description=f"查询规则库：{input_data.query}",
            metadata={"args": input_data.model_dump()},
        )
        try:
            rules = await ctx.deps.context_assembler.get_knowhow_rules(
                input_data.query,
                limit=input_data.limit,
            )
            citations = [
                AgentCitation(
                    **ctx.deps.context_assembler._build_knowhow_citation(rule, index)
                )
                for index, rule in enumerate(rules, 1)
            ]
            summary = f"命中 {len(rules)} 条规则"
            output = SearchKnowhowRulesOutput(
                summary=summary,
                rules=rules,
                citations=citations,
            )
            ctx.deps.memory.used_tools.append("search_knowhow_rules")
            ctx.deps.memory.citations.extend(citations)
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="search_knowhow_rules",
                    args=input_data.model_dump(),
                    ok=True,
                    summary=summary,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_complete(
                step_index,
                "search_knowhow_rules",
                summary,
                metadata={
                    "rule_count": len(rules),
                    "citation_count": len(citations),
                },
            )
            return output
        except Exception as exc:
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="search_knowhow_rules",
                    args=input_data.model_dump(),
                    ok=False,
                    summary=str(exc),
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_error(
                step_index,
                "search_knowhow_rules",
                str(exc),
            )
            raise
