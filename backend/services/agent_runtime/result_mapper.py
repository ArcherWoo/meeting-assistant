from __future__ import annotations

from typing import Any

from services.agent_runtime.models import AgentDeps, AgentFinalResult


def map_final_result(output: Any, deps: AgentDeps) -> AgentFinalResult:
    if isinstance(output, AgentFinalResult):
        result = output
    elif isinstance(output, dict):
        result = AgentFinalResult(**output)
    else:
        text = str(output or "").strip()
        result = AgentFinalResult(
            summary=text[:120],
            raw_text=text,
        )

    used_tools = list(dict.fromkeys([*result.used_tools, *deps.memory.used_tools]))
    citations = list(result.citations)
    for citation in deps.memory.citations:
        if citation not in citations:
            citations.append(citation)

    artifacts = list(result.artifacts)
    for artifact in deps.memory.artifacts:
        if artifact not in artifacts:
            artifacts.append(artifact)

    return result.model_copy(
        update={
            "used_tools": used_tools,
            "citations": citations,
            "artifacts": artifacts,
        }
    )

