from __future__ import annotations

from pydantic_ai import RunContext

from services.agent_runtime.models import (
    AgentArtifact,
    AgentDeps,
    AgentToolCallRecord,
    RunExcelCategoryMappingInput,
    RunExcelCategoryMappingOutput,
)
from services.classification_service import classification_service
from services.retrieval_planner import RetrievalPlannerSettings
from services.storage import utc_now_iso


def register_classification_tools(agent, policy) -> None:
    if "run_excel_category_mapping" not in policy.allowed_tools:
        return

    @agent.tool
    async def run_excel_category_mapping(
        ctx: RunContext[AgentDeps],
        input_data: RunExcelCategoryMappingInput,
    ) -> RunExcelCategoryMappingOutput:
        started_at = utc_now_iso()
        step_index = await ctx.deps.event_adapter.on_tool_start(
            "run_excel_category_mapping",
            description=f"执行 Excel 分类映射：{input_data.data_import_id}",
            metadata={"args": input_data.model_dump()},
        )
        try:
            result = await classification_service.classify_excel_files(
                template_import_id=input_data.template_import_id,
                data_import_id=input_data.data_import_id,
                template_sheet=input_data.template_sheet,
                data_sheet=input_data.data_sheet,
                name_column=input_data.name_column,
                knowhow_categories=[
                    item.strip()
                    for item in input_data.knowhow_categories.split(",")
                    if item.strip()
                ],
                mode=input_data.mode,
                review_threshold=input_data.review_threshold,
                settings=RetrievalPlannerSettings(
                    api_url=ctx.deps.api_url,
                    api_key=ctx.deps.api_key,
                    model=ctx.deps.model,
                    user_id=ctx.deps.user_id,
                ),
                user_id=ctx.deps.user_id,
                group_id=ctx.deps.group_id,
                is_admin=ctx.deps.is_admin,
            )
            output = RunExcelCategoryMappingOutput(**{key: result[key] for key in RunExcelCategoryMappingOutput.model_fields})
            ctx.deps.memory.used_tools.append("run_excel_category_mapping")
            ctx.deps.memory.artifacts.append(
                AgentArtifact(
                    type="file",
                    title=output.output_filename,
                    content=(
                        f"结果文件：{output.output_path}\n"
                        f"处理条数：{output.processed_count}\n"
                        f"命中分类：{output.matched_count}\n"
                        f"待人工复核：{output.review_count}"
                    ),
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    download_url=f"/api/agent/artifacts/classification/{output.output_filename}",
                )
            )
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="run_excel_category_mapping",
                    args=input_data.model_dump(),
                    ok=True,
                    summary=output.summary,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_complete(
                step_index,
                "run_excel_category_mapping",
                output.summary,
                metadata={
                    "output_path": output.output_path,
                    "processed_count": output.processed_count,
                    "matched_count": output.matched_count,
                    "review_count": output.review_count,
                },
            )
            return output
        except Exception as exc:
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="run_excel_category_mapping",
                    args=input_data.model_dump(),
                    ok=False,
                    summary=str(exc),
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_error(
                step_index,
                "run_excel_category_mapping",
                str(exc),
            )
            raise
