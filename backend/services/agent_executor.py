"""
Agent Executor - 任务执行引擎
遵循 PRD §2.4：用户输入 → 意图识别 → 匹配 Skill → 参数提取 → 逐步执行 → 返回结果

执行流程：
  1. Skill 匹配（关键词 + 语义）
  2. 参数提取/确认
  3. 逐步执行 Skill 步骤（调用内置工具）
  4. 实时进度反馈（SSE）
  5. 返回结构化结果
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Awaitable, Dict, List, Optional

from services.skill_manager import skill_manager
from services.skill_matcher import skill_matcher
from services.skill_parser import SkillMeta

logger = logging.getLogger(__name__)


@dataclass
class ExecutionStep:
    """单步执行结果"""
    index: int
    description: str
    status: str = "pending"  # pending / running / completed / failed
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class ExecutionContext:
    """执行上下文 - 贯穿整个 Skill 执行过程"""
    skill: SkillMeta
    params: Dict[str, Any] = field(default_factory=dict)
    steps: List[ExecutionStep] = field(default_factory=list)
    status: str = "pending"  # pending / running / completed / failed
    result: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill.id,
            "skill_name": self.skill.name,
            "params": self.params,
            "status": self.status,
            "steps": [
                {
                    "index": s.index,
                    "description": s.description,
                    "status": s.status,
                    "result": s.result,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "result": self.result,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# 工具函数类型：接收参数字典，返回结果字符串
ToolFunction = Callable[[Dict[str, Any]], Awaitable[str]]


class AgentExecutor:
    """
    Agent 执行引擎
    协调 Skill 匹配、参数提取和工具调用
    """

    def __init__(self) -> None:
        # 注册的工具函数 {tool_name: callable}
        self._tools: Dict[str, ToolFunction] = {}

    def register_tool(self, name: str, fn: ToolFunction) -> None:
        """注册一个可调用工具"""
        self._tools[name] = fn
        logger.info(f"已注册工具: {name}")

    @property
    def available_tools(self) -> List[str]:
        return list(self._tools.keys())

    async def match_skill(self, query: str) -> Optional[dict]:
        """
        根据用户输入匹配最佳 Skill
        返回: {skill: SkillMeta, score, confidence, matched_keywords} 或 None
        """
        skills = skill_manager.list_skills()
        if not skills:
            return None
        results = skill_matcher.match(query, skills)
        if not results:
            return None
        best = results[0]
        return {
            "skill_id": best.skill.id,
            "skill_name": best.skill.name,
            "score": best.score,
            "confidence": best.confidence,
            "matched_keywords": best.matched_keywords,
            "parameters": best.skill.parameters,
        }

    async def execute(
        self,
        skill_id: str,
        params: Dict[str, Any],
        llm_fn: Optional[Callable] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        执行 Skill，逐步返回进度（SSE 友好）
        每个 yield 返回一个进度事件:
          {"type": "step_start/step_complete/step_error/complete/error", ...}
        """
        skill = skill_manager.get_skill(skill_id)
        if not skill:
            yield {"type": "error", "message": f"Skill '{skill_id}' 未找到"}
            return

        ctx = ExecutionContext(
            skill=skill,
            params=params,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # 初始化步骤
        for i, step_desc in enumerate(skill.steps):
            ctx.steps.append(ExecutionStep(index=i + 1, description=step_desc))

        ctx.status = "running"
        yield {"type": "execution_start", "context": ctx.to_dict()}

        # 逐步执行
        all_results: List[str] = []
        for step in ctx.steps:
            step.status = "running"
            step.started_at = datetime.now(timezone.utc).isoformat()
            yield {"type": "step_start", "step": step.index, "description": step.description}

            try:
                result = await self._execute_step(step, ctx, llm_fn)
                step.status = "completed"
                step.result = result
                step.completed_at = datetime.now(timezone.utc).isoformat()
                all_results.append(result or "")
                yield {"type": "step_complete", "step": step.index, "result": result}
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                step.completed_at = datetime.now(timezone.utc).isoformat()
                logger.warning(f"步骤 {step.index} 执行失败: {e}")
                yield {"type": "step_error", "step": step.index, "error": str(e)}
                # 非致命错误继续执行后续步骤

        # 汇总结果
        ctx.status = "completed"
        ctx.completed_at = datetime.now(timezone.utc).isoformat()

        # 如果有 LLM，生成最终综合报告
        if llm_fn and all_results:
            try:
                summary_prompt = self._build_summary_prompt(skill, params, all_results)
                ctx.result = await llm_fn(summary_prompt)
            except Exception as e:
                logger.warning(f"生成综合报告失败: {e}")
                ctx.result = "\n\n".join(filter(None, all_results))
        else:
            ctx.result = "\n\n".join(filter(None, all_results))

        yield {"type": "complete", "context": ctx.to_dict(), "result": ctx.result}

    async def _execute_step(
        self,
        step: ExecutionStep,
        ctx: ExecutionContext,
        llm_fn: Optional[Callable] = None,
    ) -> str:
        """
        执行单个步骤
        解析步骤描述中的工具调用（如 `pptx_parser`、`knowledge_query`）
        """
        desc = step.description.lower()

        # 检测步骤中引用的工具名
        for tool_name, tool_fn in self._tools.items():
            if tool_name in desc:
                result = await tool_fn(ctx.params)
                return result

        # 如果步骤没有匹配到工具，使用 LLM 处理
        if llm_fn:
            prompt = (
                f"你正在执行采购预审任务的第 {step.index} 步。\n"
                f"步骤描述: {step.description}\n"
                f"当前参数: {json.dumps(ctx.params, ensure_ascii=False)}\n"
                f"请执行此步骤并返回结果。"
            )
            return await llm_fn(prompt)

        return f"[步骤 {step.index}] {step.description} - 已记录（无可用工具）"

    def _build_summary_prompt(
        self, skill: SkillMeta, params: Dict[str, Any], step_results: List[str],
    ) -> str:
        """构建最终综合报告的 LLM Prompt"""
        results_text = ""
        for i, r in enumerate(step_results, 1):
            if r:
                results_text += f"\n### 步骤 {i} 结果:\n{r}\n"

        output_template = skill.output_template or "请生成结构化的分析报告"

        return (
            f"你是一个专业的采购分析助手。请根据以下各步骤的执行结果，"
            f"按照指定的输出格式生成最终报告。\n\n"
            f"## 任务: {skill.name}\n"
            f"## 参数: {json.dumps(params, ensure_ascii=False)}\n\n"
            f"## 各步骤执行结果:\n{results_text}\n\n"
            f"## 输出格式要求:\n{output_template}\n\n"
            f"请生成完整的报告："
        )


# 全局单例
agent_executor = AgentExecutor()

