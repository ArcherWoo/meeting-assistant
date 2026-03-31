/**
 * 消息气泡组件
 * 用户消息右对齐，AI 消息左对齐。
 * AI 消息支持 Markdown、上下文引用、Skill 推荐和 Agent 结构化结果。
 */
import { memo } from 'react';
import clsx from 'clsx';
import ReactMarkdown, { type Components } from 'react-markdown';
import RetrievalPlanCard from '@/components/common/RetrievalPlanCard';
import StructuredPayloadView from '@/components/common/StructuredPayloadView';
import type { ContextCitation, ContextMetadata, Message, SkillSuggestionEvent } from '@/types';

interface Props {
  message: Message;
  isStreaming?: boolean;
  onApplySkillSuggestion?: (message: Message, suggestion: SkillSuggestionEvent) => void;
  onDismissSkillSuggestion?: (message: Message) => void;
}

const markdownComponents: Components = {
  p: ({ children }) => <p className="my-2 whitespace-pre-wrap">{children}</p>,
  h1: ({ children }) => <h1 className="mt-4 mb-2 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-4 mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 mb-2 text-sm font-semibold">{children}</h3>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="whitespace-pre-wrap">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-4 border-primary/35 bg-surface/80 px-3 py-2 text-text-secondary dark:bg-dark-sidebar/70 dark:text-text-dark-secondary">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-primary underline decoration-primary/35 underline-offset-2 hover:decoration-primary"
    >
      {children}
    </a>
  ),
  code: ({ className, children }) => {
    const code = String(children).replace(/\n$/, '');
    const match = /language-([\w-]+)/.exec(className || '');
    const isBlockCode = Boolean(match) || code.includes('\n');

    if (isBlockCode) {
      return (
        <div className="my-3 overflow-x-auto rounded-xl border border-surface-divider bg-slate-950/95 shadow-sm dark:border-dark-divider dark:bg-slate-950">
          {match?.[1] && (
            <div className="border-b border-white/10 px-3 py-2 text-[10px] uppercase tracking-[0.12em] text-slate-300">
              {match[1]}
            </div>
          )}
          <pre className="m-0 p-4 text-[12px] leading-6 text-slate-100">
            <code className="font-mono">{code}</code>
          </pre>
        </div>
      );
    }

    return (
      <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.92em] text-slate-700 dark:bg-slate-800 dark:text-slate-100">
        {children}
      </code>
    );
  },
};

function renderContextBadge(label: string, value: number, tone: 'blue' | 'emerald' | 'amber') {
  const toneClassMap = {
    blue: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300',
    amber: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300',
  };

  return (
    <span key={label} className={clsx('win-badge px-2 py-1 text-[10px]', toneClassMap[tone])}>
      {label} {value}
    </span>
  );
}

function renderCitationIcon(sourceType: ContextCitation['source_type']): string {
  if (sourceType === 'knowledge') return '📚';
  if (sourceType === 'knowhow') return '📋';
  if (sourceType === 'file') return '📎';
  return '🛠️';
}

function renderCitationTypeBadge(sourceType: ContextCitation['source_type']): string {
  if (sourceType === 'knowledge') return '知识库';
  if (sourceType === 'knowhow') return 'Know-how';
  if (sourceType === 'file') return '文件';
  return 'Skill';
}

function getCitationSourceHeading(citation: ContextCitation): string {
  return citation.file_name ? '文件名' : '来源';
}

function getCitationSourceText(citation: ContextCitation): string {
  return citation.file_name || citation.label || citation.title || '未命名来源';
}

function getCitationLocationText(citation: ContextCitation): string {
  const parts = [citation.title, citation.location]
    .map((part) => part?.trim())
    .filter((part): part is string => Boolean(part));

  const uniqueParts = Array.from(new Set(parts));
  return uniqueParts.join(' · ') || '未提供定位信息';
}

function getCitationSummaryText(citation: ContextCitation): string {
  return citation.snippet?.trim() || '未提供摘要';
}

function buildCitationGroups(citations: ContextCitation[]) {
  return ([
    { key: 'knowledge', label: '知识库引用', items: citations.filter((citation) => citation.source_type === 'knowledge') },
    { key: 'knowhow', label: 'Know-how 引用', items: citations.filter((citation) => citation.source_type === 'knowhow') },
    { key: 'skill', label: 'Skill 引用', items: citations.filter((citation) => citation.source_type === 'skill') },
    { key: 'file', label: '文件引用', items: citations.filter((citation) => citation.source_type === 'file') },
  ] as Array<{ key: ContextCitation['source_type']; label: string; items: ContextCitation[] }>)
    .filter((group) => group.items.length > 0);
}

function areSameCitationSet(left: ContextCitation[], right: ContextCitation[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((citation, index) => citation.id === right[index]?.id);
}

function getContextCountSummary(context: ContextMetadata, kind: 'injected' | 'retrieved'): string {
  const knowledgeCount = kind === 'retrieved'
    ? (context.retrieved_knowledge_count ?? context.knowledge_count)
    : context.knowledge_count;
  const knowhowCount = kind === 'retrieved'
    ? (context.retrieved_knowhow_count ?? context.knowhow_count)
    : context.knowhow_count;
  const skillCount = kind === 'retrieved'
    ? (context.retrieved_skill_count ?? context.skill_count)
    : context.skill_count;

  const parts = [
    knowledgeCount ? `知识库 ${knowledgeCount}` : '',
    knowhowCount ? `Know-how ${knowhowCount}` : '',
    skillCount ? `Skill ${skillCount}` : '',
  ].filter(Boolean);

  return parts.length > 0 ? parts.join(' / ') : '无引用来源';
}

function MessageBubble({
  message,
  isStreaming = false,
  onApplySkillSuggestion,
  onDismissSkillSuggestion,
}: Props) {
  const isUser = message.role === 'user';
  const isError = message.content.startsWith('⚠️');
  const senderLabel = isUser ? '你' : '智枢';
  const context = message.metadata?.context;
  const agentResult = message.metadata?.agentResult;
  const skillSuggestion = message.metadata?.skillSuggestion;
  const citations = context?.citations ?? [];
  const retrievedCitations = context?.retrieved_citations?.length
    ? context.retrieved_citations
    : citations;
  const groupedCitations = buildCitationGroups(citations);
  const groupedRetrievedCitations = buildCitationGroups(retrievedCitations);
  const showRetrievedCitations = Boolean(
    context?.truncated
    && context?.retrieved_citations?.length
    && !areSameCitationSet(citations, retrievedCitations),
  );
  const hasContextMetadata = Boolean(
    context && (
      context.knowledge_count
      || context.knowhow_count
      || context.skill_count
      || context.summary
      || context.retrieval_plan
      || citations.length
    ),
  );

  return (
    <div
      className={clsx(
        'mb-4 flex items-start gap-3 animate-fade-in',
        isUser ? 'justify-end' : 'justify-start',
      )}
    >
      {!isUser && (
        <div className="mt-5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-white text-sm shadow-sm dark:border-dark-divider dark:bg-dark-card">
          <span className="text-sm">🍒</span>
        </div>
      )}

      <div className="min-w-0 max-w-[78%]">
        <div className={clsx('mb-1 px-1 text-[11px] text-text-secondary', isUser && 'text-right')}>
          {senderLabel}
        </div>

        {!isUser && !isError && (hasContextMetadata || skillSuggestion) && (
          <div className="mb-2 space-y-1 px-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {context?.knowledge_count
                ? renderContextBadge('📚 知识库', context.knowledge_count, 'blue')
                : null}
              {context?.knowhow_count
                ? renderContextBadge('📋 Know-how', context.knowhow_count, 'emerald')
                : null}
              {context?.skill_count
                ? renderContextBadge('🛠️ Skill', context.skill_count, 'amber')
                : null}
              {skillSuggestion && (
                <span className="win-badge border-primary/20 bg-primary/10 px-2 py-1 text-[10px] text-primary">
                  已推荐技能
                </span>
              )}
            </div>
            {context?.summary && (
              <p className="text-[11px] text-text-secondary dark:text-text-dark-secondary">
                已参考：{context.summary}
              </p>
            )}
            {context?.truncated && (
              <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-[11px] leading-5 text-amber-800 shadow-sm dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                <p className="font-medium">上下文已按预算裁剪</p>
                <p className="mt-1">
                  实际注入：{getContextCountSummary(context, 'injected')}
                </p>
                <p className="mt-1">
                  原始召回：{context.retrieved_summary || getContextCountSummary(context, 'retrieved')}
                </p>
              </div>
            )}
            {context?.retrieval_plan && (
              <RetrievalPlanCard
                plan={context.retrieval_plan}
                compact
                title="检索规划"
              />
            )}
            {groupedCitations.length > 0 && (
              <details className="group overflow-hidden rounded-lg border border-surface-divider/80 bg-white/80 shadow-sm dark:border-dark-divider dark:bg-dark-card/70">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-medium text-text-secondary marker:content-none dark:text-text-dark-secondary">
                  <span>
                    引用来源
                    {showRetrievedCitations
                      ? ` (注入 ${citations.length} / 召回 ${retrievedCitations.length})`
                      : ` (${citations.length})`}
                  </span>
                  <span className="text-[10px] transition-transform group-open:rotate-180">⌄</span>
                </summary>
                <div className="space-y-3 border-t border-surface-divider/80 px-3 py-3 dark:border-dark-divider">
                  <div className="space-y-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                      已注入回答
                    </p>
                    <p className="text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                      {context ? getContextCountSummary(context, 'injected') : '无引用来源'}
                    </p>
                  </div>
                  {groupedCitations.map((group) => (
                    <div key={group.key} className="space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                        {group.label}
                      </p>
                      <div className="space-y-2">
                        {group.items.map((citation) => (
                          <div
                            key={citation.id}
                            className="rounded-xl border border-surface-divider bg-surface-card px-3 py-3 dark:border-dark-divider dark:bg-dark-sidebar/70"
                          >
                            <div className="flex items-start gap-3">
                              <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-white text-sm shadow-sm dark:border-dark-divider dark:bg-dark-card">
                                <span>{renderCitationIcon(citation.source_type)}</span>
                              </div>
                              <div className="min-w-0 flex-1 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="win-badge border-surface-divider bg-white/90 px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary">
                                    {renderCitationTypeBadge(citation.source_type)}
                                  </span>
                                  {citation.page ? (
                                    <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary">
                                      P{citation.page}
                                    </span>
                                  ) : null}
                                </div>

                                <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                    {getCitationSourceHeading(citation)}
                                  </p>
                                  <p className="mt-1 break-all text-[12px] font-semibold text-text-primary dark:text-text-dark-primary">
                                    {getCitationSourceText(citation)}
                                  </p>
                                </div>

                                <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                    位置
                                  </p>
                                  <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                    {getCitationLocationText(citation)}
                                  </p>
                                </div>

                                <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                    摘要
                                  </p>
                                  <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                    {getCitationSummaryText(citation)}
                                  </p>
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  {showRetrievedCitations && (
                    <>
                      <div className="border-t border-dashed border-surface-divider pt-3 dark:border-dark-divider" />
                      <div className="space-y-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                          原始召回（未全部注入）
                        </p>
                        <p className="text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                          {context ? (context.retrieved_summary || getContextCountSummary(context, 'retrieved')) : '无原始召回信息'}
                        </p>
                      </div>
                      {groupedRetrievedCitations.map((group) => (
                        <div key={`retrieved-${group.key}`} className="space-y-2">
                          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                            {group.label}
                          </p>
                          <div className="space-y-2">
                            {group.items.map((citation) => (
                              <div
                                key={`retrieved-${citation.id}`}
                                className="rounded-xl border border-dashed border-surface-divider bg-surface-card/70 px-3 py-3 dark:border-dark-divider dark:bg-dark-sidebar/40"
                              >
                                <div className="flex items-start gap-3">
                                  <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-white text-sm shadow-sm dark:border-dark-divider dark:bg-dark-card">
                                    <span>{renderCitationIcon(citation.source_type)}</span>
                                  </div>
                                  <div className="min-w-0 flex-1 space-y-2">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className="win-badge border-surface-divider bg-white/90 px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary">
                                        {renderCitationTypeBadge(citation.source_type)}
                                      </span>
                                      {citation.page ? (
                                        <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary">
                                          P{citation.page}
                                        </span>
                                      ) : null}
                                    </div>

                                    <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                        {getCitationSourceHeading(citation)}
                                      </p>
                                      <p className="mt-1 break-all text-[12px] font-semibold text-text-primary dark:text-text-dark-primary">
                                        {getCitationSourceText(citation)}
                                      </p>
                                    </div>

                                    <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                        位置
                                      </p>
                                      <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                        {getCitationLocationText(citation)}
                                      </p>
                                    </div>

                                    <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 dark:border-dark-divider dark:bg-dark-card/80">
                                      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                        摘要
                                      </p>
                                      <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                        {getCitationSummaryText(citation)}
                                      </p>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </details>
            )}
          </div>
        )}

        <div
          className={clsx(
            'overflow-hidden px-4 py-3 text-[13px] leading-6 shadow-sm',
            isUser
              ? 'rounded-xl rounded-tr-sm bg-primary text-white'
              : isError
                ? 'rounded-xl rounded-tl-sm border border-red-200 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400'
                : 'rounded-xl rounded-tl-sm border border-surface-divider bg-white text-text-primary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-primary',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : isStreaming ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : message.content ? (
            <div className="markdown-body text-[13px] leading-6">
              <ReactMarkdown components={markdownComponents}>
                {message.content}
              </ReactMarkdown>
            </div>
          ) : (
            <span className="inline-flex items-center gap-1 text-text-secondary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse [animation-delay:300ms]" />
            </span>
          )}

          {!isUser && !isError && skillSuggestion && (
            <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/80 p-3 dark:border-blue-800 dark:bg-blue-900/20">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md border border-blue-200 bg-white text-base shadow-sm dark:border-blue-800 dark:bg-blue-950/40">
                  🛠️
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                    推荐技能：{skillSuggestion.skill_name}
                  </p>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                    {skillSuggestion.description}
                  </p>
                  <p className="mt-2 text-[11px] text-text-secondary dark:text-text-dark-secondary">
                    匹配度 {Math.round(skillSuggestion.score * 100)}% · 置信度 {skillSuggestion.confidence}
                  </p>
                  {skillSuggestion.matched_keywords?.length ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {skillSuggestion.matched_keywords.map((keyword) => (
                        <span
                          key={keyword}
                          className="win-chip border-blue-200 bg-white/90 text-[10px] text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300"
                        >
                          {keyword}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  onClick={() => onApplySkillSuggestion?.(message, skillSuggestion)}
                  className="win-button-primary h-8 px-3 text-xs"
                >
                  应用到输入框
                </button>
                <button
                  onClick={() => onDismissSkillSuggestion?.(message)}
                  className="win-button-subtle h-8 px-2 text-xs"
                >
                  忽略
                </button>
              </div>
            </div>
          )}

          {!isUser && !isError && agentResult && (
            <div className="mt-4 space-y-3 rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 dark:border-emerald-800 dark:bg-emerald-900/10">
              <div className="flex flex-wrap items-center gap-2">
                <span className="win-badge border-emerald-200 bg-white/90 px-2 py-1 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
                  Agent 结果
                </span>
                {agentResult.used_tools.map((tool) => (
                  <span
                    key={tool}
                    className="win-chip border-emerald-200 bg-white/90 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
                  >
                    {tool}
                  </span>
                ))}
              </div>

              {agentResult.summary && (
                <div className="rounded-lg border border-emerald-200/70 bg-white/80 px-3 py-2 dark:border-emerald-800/70 dark:bg-emerald-950/20">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                    执行摘要
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-[12px] leading-5 text-text-primary dark:text-text-dark-primary">
                    {agentResult.summary}
                  </p>
                </div>
              )}

              {agentResult.structured_payload && Object.keys(agentResult.structured_payload).length > 0 && (
                <div className="rounded-lg border border-emerald-200/70 bg-white/80 px-3 py-2 dark:border-emerald-800/70 dark:bg-emerald-950/20">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                    结构化结果
                  </p>
                  <div className="mt-2">
                    <StructuredPayloadView data={agentResult.structured_payload} />
                  </div>
                </div>
              )}

              {agentResult.artifacts.length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                    产物
                  </p>
                  {agentResult.artifacts.map((artifact, index) => (
                    <div
                      key={`${artifact.type}-${artifact.title}-${index}`}
                      className="rounded-lg border border-emerald-200/70 bg-white/80 px-3 py-2 dark:border-emerald-800/70 dark:bg-emerald-950/20"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="win-badge border-emerald-200 bg-emerald-50 px-2 py-1 text-[10px] text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300">
                          {artifact.type}
                        </span>
                        <span className="text-[12px] font-medium text-text-primary dark:text-text-dark-primary">
                          {artifact.title}
                        </span>
                        {artifact.mime_type && (
                          <span className="text-[10px] text-text-secondary dark:text-text-dark-secondary">
                            {artifact.mime_type}
                          </span>
                        )}
                      </div>
                      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-black/5 p-3 text-[11px] leading-5 dark:bg-white/5">
                        {artifact.content}
                      </pre>
                    </div>
                  ))}
                </div>
              )}

              {agentResult.next_actions.length > 0 && (
                <div className="rounded-lg border border-emerald-200/70 bg-white/80 px-3 py-2 dark:border-emerald-800/70 dark:bg-emerald-950/20">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                    下一步建议
                  </p>
                  <div className="mt-2 space-y-1.5">
                    {agentResult.next_actions.map((action, index) => (
                      <p key={`${action}-${index}`} className="text-[12px] leading-5 text-text-primary dark:text-text-dark-primary">
                        {index + 1}. {action}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {isUser && (
        <div className="mt-5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-primary shadow-sm">
          <span className="text-xs font-medium text-white">U</span>
        </div>
      )}
    </div>
  );
}

export default memo(MessageBubble);
