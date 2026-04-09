from __future__ import annotations

from services.agent_runtime.toolsets.file_tools import register_file_tools
from services.agent_runtime.toolsets.classification_tools import register_classification_tools
from services.agent_runtime.toolsets.knowledge_tools import register_knowledge_tools
from services.agent_runtime.toolsets.knowhow_tools import register_knowhow_tools
from services.agent_runtime.toolsets.skill_tools import register_skill_tools


def register_agent_tools(agent, policy) -> None:
    register_skill_tools(agent, policy)
    register_file_tools(agent, policy)
    register_classification_tools(agent, policy)
    register_knowledge_tools(agent, policy)
    register_knowhow_tools(agent, policy)
