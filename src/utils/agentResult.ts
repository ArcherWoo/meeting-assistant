import type {
  AgentFinalResult,
  AgentResultSnapshot,
  ContextCitation,
  ContextMetadata,
  MessageMetadata,
} from '@/types';

const CONTEXT_CITATION_SOURCES = new Set<ContextCitation['source_type']>([
  'knowledge',
  'knowhow',
  'skill',
  'file',
]);

function toContextCitation(
  citation: AgentFinalResult['citations'][number],
  index: number,
): ContextCitation {
  const sourceType = CONTEXT_CITATION_SOURCES.has(citation.source_type)
    ? citation.source_type
    : 'knowledge';

  const title = citation.title?.trim() || citation.label?.trim() || `${sourceType} citation ${index + 1}`;
  const label = citation.label?.trim() || title;

  return {
    id: `${sourceType}-${label}-${index}`,
    source_type: sourceType,
    label,
    title,
    snippet: citation.snippet?.trim() || '未提供摘要',
    location: citation.location?.trim() || undefined,
    file_name: sourceType === 'file' ? label : undefined,
  };
}

function buildAgentContextMetadata(result: AgentFinalResult): ContextMetadata | undefined {
  const citations = result.citations.map(toContextCitation);
  const knowledgeCount = citations.filter((item) => item.source_type === 'knowledge').length;
  const knowhowCount = citations.filter((item) => item.source_type === 'knowhow').length;
  const skillCount = citations.filter((item) => item.source_type === 'skill').length;

  if (!citations.length && !result.summary.trim()) {
    return undefined;
  }

  return {
    knowledge_count: knowledgeCount,
    knowhow_count: knowhowCount,
    skill_count: skillCount,
    summary: result.summary?.trim() || 'Agent 已完成执行',
    citations,
  };
}

function buildAgentResultSnapshot(result: AgentFinalResult, runId?: string): AgentResultSnapshot {
  return {
    ...(runId ? { runId } : {}),
    summary: result.summary,
    raw_text: result.raw_text,
    used_tools: [...result.used_tools],
    citations: result.citations.map(toContextCitation),
    artifacts: result.artifacts.map((artifact) => ({ ...artifact })),
    next_actions: [...result.next_actions],
    structured_payload: result.structured_payload,
  };
}

export interface AgentWriteBackPayload {
  content: string;
  metadata?: MessageMetadata;
}

export function buildAgentWriteBackPayload(result: AgentFinalResult, runId?: string): AgentWriteBackPayload {
  const content = result.raw_text?.trim() || result.summary?.trim() || '（Agent 已完成执行）';
  const context = buildAgentContextMetadata(result);
  const agentResult = buildAgentResultSnapshot(result, runId);

  return {
    content,
    metadata: {
      ...(context ? { context } : {}),
      agentResult,
    },
  };
}
