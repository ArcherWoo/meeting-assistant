from __future__ import annotations

from pydantic_ai import RunContext

from services.agent_runtime.errors import AgentToolExecutionError
from services.agent_runtime.models import (
    AgentCitation,
    AgentDeps,
    AgentToolCallRecord,
    ExtractFileTextInput,
    ExtractFileTextOutput,
)
from services.storage import utc_now_iso


def register_file_tools(agent, policy) -> None:
    if "extract_file_text" not in policy.allowed_tools:
        return

    @agent.tool
    async def extract_file_text(
        ctx: RunContext[AgentDeps],
        input_data: ExtractFileTextInput,
    ) -> ExtractFileTextOutput:
        started_at = utc_now_iso()
        requested_source = input_data.import_id or input_data.filename or "unknown"
        step_index = await ctx.deps.event_adapter.on_tool_start(
            "extract_file_text",
            description=f"提取文件文本：{requested_source}",
            metadata={"args": input_data.model_dump(exclude_none=True)},
        )
        try:
            if input_data.import_id:
                rows = await ctx.deps.storage._fetchall(
                    "SELECT source_file, content FROM knowledge_chunks "
                    "WHERE import_id=? ORDER BY chunk_index ASC",
                    (input_data.import_id,),
                )
            else:
                rows = await ctx.deps.storage._fetchall(
                    "SELECT source_file, content FROM knowledge_chunks "
                    "WHERE source_file=? ORDER BY chunk_index ASC",
                    (input_data.filename,),
                )

            if not rows:
                raise AgentToolExecutionError("未找到对应文件文本")

            source = str(rows[0].get("source_file") or input_data.filename or input_data.import_id)
            text = "\n\n".join(str(row.get("content") or "").strip() for row in rows if str(row.get("content") or "").strip())
            if not text:
                raise AgentToolExecutionError("文件存在，但没有可用文本")

            output = ExtractFileTextOutput(
                source=source,
                text=text,
                char_count=len(text),
            )
            citation = AgentCitation(
                source_type="file",
                label=source,
                title=source,
                snippet=text[:180],
                location=f"{len(rows)} 个片段",
            )
            summary = f"已提取 {source}，共 {len(text)} 字符"
            ctx.deps.memory.used_tools.append("extract_file_text")
            ctx.deps.memory.citations.append(citation)
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="extract_file_text",
                    args=input_data.model_dump(exclude_none=True),
                    ok=True,
                    summary=summary,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_complete(
                step_index,
                "extract_file_text",
                summary,
                metadata={
                    "source": source,
                    "char_count": len(text),
                    "chunk_count": len(rows),
                },
            )
            return output
        except Exception as exc:
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="extract_file_text",
                    args=input_data.model_dump(exclude_none=True),
                    ok=False,
                    summary=str(exc),
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_error(
                step_index,
                "extract_file_text",
                str(exc),
            )
            raise
