from __future__ import annotations

from pydantic_ai import RunContext

from services.agent_runtime.models import (
    AgentCitation,
    AgentDeps,
    AgentToolCallRecord,
    QueryKnowledgeInput,
    QueryKnowledgeOutput,
)
from services.storage import utc_now_iso


def register_knowledge_tools(agent, policy) -> None:
    if "query_knowledge" not in policy.allowed_tools:
        return

    @agent.tool
    async def query_knowledge(
        ctx: RunContext[AgentDeps],
        input_data: QueryKnowledgeInput,
    ) -> QueryKnowledgeOutput:
        started_at = utc_now_iso()
        step_index = await ctx.deps.event_adapter.on_tool_start(
            "query_knowledge",
            description=f"查询知识库：{input_data.query}",
            metadata={"args": input_data.model_dump()},
        )
        try:
            items = await ctx.deps.context_assembler.search_knowledge(
                input_data.query,
                limit=input_data.limit,
            )
            citations = [
                AgentCitation(**ctx.deps.context_assembler._build_knowledge_citation(result, index))
                for index, result in enumerate(items, 1)
            ]
            summary = f"命中 {len(items)} 条知识库结果"
            output = QueryKnowledgeOutput(
                summary=summary,
                items=items,
                citations=citations,
            )
            ctx.deps.memory.used_tools.append("query_knowledge")
            for citation in output.citations:
                ctx.deps.memory.citations.append(citation)
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="query_knowledge",
                    args=input_data.model_dump(),
                    ok=True,
                    summary=summary,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_complete(
                step_index,
                "query_knowledge",
                summary,
                metadata={
                    "result_count": len(items),
                    "citation_count": len(output.citations),
                },
            )
            return output
        except Exception as exc:
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="query_knowledge",
                    args=input_data.model_dump(),
                    ok=False,
                    summary=str(exc),
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_error(
                step_index,
                "query_knowledge",
                str(exc),
            )
            raise
