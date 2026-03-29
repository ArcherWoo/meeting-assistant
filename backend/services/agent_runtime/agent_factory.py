from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from services.agent_runtime.models import AgentDeps, AgentFinalResult
from services.agent_runtime.tools import register_agent_tools


def create_runtime_agent(deps: AgentDeps) -> Agent[AgentDeps, AgentFinalResult]:
    provider = OpenAIProvider(
        base_url=deps.api_url,
        api_key=deps.api_key,
    )
    model = OpenAIChatModel(
        deps.model,
        provider=provider,
    )
    agent = Agent(
        model=model,
        deps_type=AgentDeps,
        output_type=AgentFinalResult,
        instructions=deps.policy.instructions,
        retries=1,
        defer_model_check=True,
    )
    register_agent_tools(agent, deps.policy)
    return agent

