/**
 * 消息气泡组件
 * 用户消息右对齐，AI 消息左对齐。
 * AI 消息支持 Markdown、上下文引用、Skill 推荐和 Agent 结构化结果。
 */
import { lazy, memo, Suspense, useState } from 'react';
import clsx from 'clsx';
import type { ChatGenerationPhase, ContextCitation, ContextMetadata, GenerationPreview, Message, SkillSuggestionEvent } from '@/types';

const RichMarkdown = lazy(() => import('@/components/chat/RichMarkdown'));
const RetrievalPlanCard = lazy(() => import('@/components/common/RetrievalPlanCard'));
const StructuredPayloadView = lazy(() => import('@/components/common/StructuredPayloadView'));

interface Props {
  message: Message;
  isStreaming?: boolean;
  onApplySkillSuggestion?: (message: Message, suggestion: SkillSuggestionEvent) => void;
  onDismissSkillSuggestion?: (message: Message) => void;
  onRetryGeneration?: (message: Message) => void;
  canRetryGeneration?: boolean;
}

type CopyState = 'idle' | 'done' | 'error';

function IconCopy() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true" className="h-[15px] w-[15px]">
      <rect x="7" y="3" width="10" height="10" rx="2" />
      <path d="M5 7H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-1" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true" className="h-[15px] w-[15px]">
      <path d="m4.5 10.5 3.5 3.5 7-8" />
    </svg>
  );
}

function IconAlert() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true" className="h-[15px] w-[15px]">
      <path d="M10 3.5 17 16.5H3L10 3.5Z" />
      <path d="M10 7.4v4.2" />
      <circle cx="10" cy="14" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  );
}

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

function getCitationLocatorChips(citation: ContextCitation): string[] {
  const chips: string[] = [];
  if (citation.sheet) chips.push(citation.sheet);
  if (citation.row_start && citation.row_end) {
    chips.push(citation.row_start === citation.row_end ? `R${citation.row_start}` : `R${citation.row_start}-${citation.row_end}`);
  }
  if (citation.story) chips.push(citation.story);
  if (citation.table_title) chips.push(citation.table_title);
  if (citation.ocr_segment_index) chips.push(`OCR #${citation.ocr_segment_index}`);
  if (citation.chunk_index) chips.push(`Chunk #${citation.chunk_index}`);
  return chips;
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

function getAttachmentSummary(message: Message): string[] {
  return (message.attachments ?? []).map((attachment) => {
    const parts = [attachment.fileType.toUpperCase()];
    if (attachment.fileSize) {
      const size = attachment.fileSize < 1024
        ? `${attachment.fileSize}B`
        : attachment.fileSize < 1024 * 1024
          ? `${(attachment.fileSize / 1024).toFixed(1)}KB`
          : `${(attachment.fileSize / (1024 * 1024)).toFixed(1)}MB`;
      parts.push(size);
    }
    if (attachment.charCount) {
      parts.push(`${attachment.charCount} 字符`);
    }
    return parts.filter(Boolean).join(' · ');
  });
}

function getGenerationPhaseLabel(phase?: ChatGenerationPhase): string {
  if (phase === 'retrieving') return '正在检索上下文';
  if (phase === 'calling_model') return '正在请求模型';
  if (phase === 'streaming') return '正在生成回答';
  return '正在准备回答';
}

function AssistantPendingState({
  phase,
  detail,
  preview,
}: {
  phase?: ChatGenerationPhase;
  detail?: string;
  preview?: GenerationPreview;
}) {
  return (
    <div className="min-w-[280px] max-w-[520px] rounded-2xl border border-surface-divider/90 bg-white/95 px-4 py-4 shadow-[0_14px_32px_rgba(15,23,42,0.06)] dark:border-dark-divider dark:bg-dark-card">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-2.5 w-2.5 rounded-full bg-primary animate-pulse" />
        <span className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">
          {getGenerationPhaseLabel(phase)}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-text-secondary dark:text-text-dark-secondary">
        {detail?.trim() || '模型开始输出后会立即显示。'}
      </p>
      {preview?.title && (
        <div className="mt-3 rounded-xl border border-primary/10 bg-primary/5 px-3 py-3">
          <p className="text-[12px] font-medium text-text-primary dark:text-text-dark-primary">
            {preview.title}
          </p>
          {preview.steps.length > 0 && (
            <div className="mt-2 space-y-1.5">
              {preview.steps.map((step, index) => (
                <p
                  key={`${step}-${index}`}
                  className="text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary"
                >
                  {index + 1}. {step}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="mt-4 space-y-2">
        <div className="h-2.5 w-[82%] rounded-full bg-slate-200/90 dark:bg-slate-700/70 animate-pulse" />
        <div className="h-2.5 w-[68%] rounded-full bg-slate-200/80 dark:bg-slate-700/60 animate-pulse [animation-delay:150ms]" />
        <div className="h-2.5 w-[56%] rounded-full bg-slate-200/70 dark:bg-slate-700/50 animate-pulse [animation-delay:300ms]" />
      </div>
    </div>
  );
}

function CopyMessageButton({
  copyState,
  onCopy,
  tone,
}: {
  copyState: CopyState;
  onCopy: () => void;
  tone: 'user' | 'assistant';
}) {
  const isUserTone = tone === 'user';
  const idleClasses = isUserTone
    ? 'border-white/0 bg-white/10 text-white/72 hover:border-white/18 hover:bg-white/16 hover:text-white'
    : 'border-surface-divider/0 bg-surface-card/72 text-text-secondary/75 hover:border-surface-divider/80 hover:bg-white/96 hover:text-text-primary dark:bg-dark-card/75 dark:text-text-dark-secondary dark:hover:border-dark-divider dark:hover:bg-dark-card dark:hover:text-text-dark-primary';
  const doneClasses = isUserTone
    ? 'border-emerald-200/35 bg-emerald-500/18 text-white'
    : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300';
  const errorClasses = isUserTone
    ? 'border-rose-200/35 bg-rose-500/18 text-white'
    : 'border-red-200 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300';

  return (
    <button
      type="button"
      onClick={onCopy}
      className={clsx(
        'inline-flex h-7 w-7 items-center justify-center rounded-full border shadow-sm transition-all backdrop-blur-sm opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
        copyState === 'done' ? doneClasses : copyState === 'error' ? errorClasses : idleClasses,
      )}
      title="复制这条消息"
      aria-label="复制这条消息"
    >
      {copyState === 'done' ? (
        <IconCheck />
      ) : copyState === 'error' ? (
        <IconAlert />
      ) : (
        <IconCopy />
      )}
    </button>
  );
}

function MessageBubble({
  message,
  isStreaming = false,
  onApplySkillSuggestion,
  onDismissSkillSuggestion,
  onRetryGeneration,
  canRetryGeneration = false,
}: Props) {
  const [copyState, setCopyState] = useState<CopyState>('idle');
  const isUser = message.role === 'user';
  const generationPhase = message.metadata?.generationPhase;
  const generationStatusText = message.metadata?.generationStatusText;
  const generationPreview = message.metadata?.generationPreview;
  const generationState = message.metadata?.generationState;
  const generationError = message.metadata?.generationError;
  const isError = generationState === 'error' && message.content.trim() === '本次生成失败，请重试。';
  const senderLabel = isUser ? '你' : '智枢';
  const context = message.metadata?.context;
  const agentResult = message.metadata?.agentResult;
  const skillSuggestion = message.metadata?.skillSuggestion;
  const attachments = message.attachments ?? [];
  const attachmentSummaries = getAttachmentSummary(message);
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
  const canCopyMessage = Boolean(message.content?.trim());

  const handleCopyMessage = async () => {
    const text = message.content?.trim();
    if (!text) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', 'true');
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopyState('done');
    } catch {
      setCopyState('error');
    }

    window.setTimeout(() => {
      setCopyState('idle');
    }, 1600);
  };

  return (
    <div
      className={clsx(
        'group mb-4 flex items-start gap-3 animate-fade-in',
        isUser ? 'justify-end' : 'justify-start',
      )}
    >
      {!isUser && (
        <div className="mt-5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-white text-sm shadow-sm dark:border-dark-divider dark:bg-dark-card">
          <span className="text-sm">🍒</span>
        </div>
      )}

      <div className="relative min-w-0 max-w-[78%]">
        <div className={clsx(
          'mb-1 px-1 text-[11px] text-text-secondary',
          isUser && 'text-right',
        )}>
          <span>{senderLabel}</span>
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
              <Suspense fallback={null}>
                <RetrievalPlanCard
                  plan={context.retrieval_plan}
                  compact
                  title="检索规划"
                />
              </Suspense>
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
                                  {getCitationLocatorChips(citation).map((chip) => (
                                    <span
                                      key={`${citation.id}-${chip}`}
                                      className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary"
                                    >
                                      {chip}
                                    </span>
                                  ))}
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
                                      {getCitationLocatorChips(citation).map((chip) => (
                                        <span
                                          key={`retrieved-${citation.id}-${chip}`}
                                          className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary"
                                        >
                                          {chip}
                                        </span>
                                      ))}
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
            'relative overflow-visible px-4 py-3 text-[13px] leading-6 shadow-sm',
            isUser && 'select-text cursor-text [user-select:text] [-webkit-user-select:text]',
            isUser
              ? 'rounded-[20px] rounded-tr-md border border-[#3F6DF6] bg-[#4B74F8] pr-11 pb-4 text-white [box-shadow:0_10px_24px_rgba(75,116,248,0.28)]'
              : isError
                ? 'rounded-xl rounded-tl-sm border border-red-200 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400'
                : 'rounded-xl rounded-tl-sm border border-surface-divider bg-white pr-10 text-text-primary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-primary',
          )}
        >
          {canCopyMessage && (
            <div className="absolute right-2 top-2 z-10">
              <CopyMessageButton
                copyState={copyState}
                onCopy={() => { void handleCopyMessage(); }}
                tone={isUser ? 'user' : 'assistant'}
              />
            </div>
          )}
          {isUser ? (
            <>
              <p className="whitespace-pre-wrap select-text [user-select:text] [-webkit-user-select:text]">
                {message.content}
              </p>
              {attachments.length > 0 && (
                <div className="mt-3 space-y-2">
                  {attachments.map((attachment, index) => (
                    <div
                      key={attachment.id || `${attachment.fileName}-${index}`}
                      className="rounded-xl border border-white/24 bg-white/14 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
                    >
                      <p className="truncate text-xs font-medium">{attachment.fileName}</p>
                      {attachmentSummaries[index] && (
                        <p className="mt-1 text-[11px] text-white/78">{attachmentSummaries[index]}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : isStreaming && message.content ? (
            <>
              <Suspense fallback={<p className="whitespace-pre-wrap">{message.content}</p>}>
                <RichMarkdown content={message.content} streaming />
              </Suspense>
              <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-2.5 py-1 text-[11px] text-primary">
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                <span>{generationStatusText || getGenerationPhaseLabel(generationPhase)}</span>
              </div>
            </>
          ) : message.content ? (
            <Suspense fallback={<p className="whitespace-pre-wrap">{message.content}</p>}>
              <RichMarkdown content={message.content} />
            </Suspense>
          ) : generationPhase ? (
            <AssistantPendingState
              phase={generationPhase}
              detail={generationStatusText}
              preview={generationPreview}
            />
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

          {!isUser && generationState && (
            <div
              className={clsx(
                'mt-4 rounded-lg border p-3',
                generationState === 'error'
                  ? 'border-red-200 bg-red-50/80 dark:border-red-800 dark:bg-red-900/20'
                  : 'border-amber-200 bg-amber-50/80 dark:border-amber-800 dark:bg-amber-900/20',
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={clsx(
                    'win-badge px-2 py-1 text-[10px]',
                    generationState === 'error'
                      ? 'border-red-200 bg-white/90 text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300'
                      : 'border-amber-200 bg-white/90 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300',
                  )}
                >
                  {generationState === 'error' ? '生成失败' : '已停止生成'}
                </span>
              </div>
              <p
                className={clsx(
                  'mt-2 text-[12px] leading-5',
                  generationState === 'error'
                    ? 'text-red-700 dark:text-red-300'
                    : 'text-amber-800 dark:text-amber-300',
                )}
              >
                {generationState === 'error'
                  ? '这次回答没有完整生成，你可以直接重新生成。'
                  : '这次回答已按你的操作停止，当前内容已经保留。'}
              </p>
              {generationError && (
                <p className="mt-2 whitespace-pre-wrap text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                  详情：{generationError}
                </p>
              )}
              {onRetryGeneration && canRetryGeneration && (
                <div className="mt-3">
                  <button
                    onClick={() => onRetryGeneration(message)}
                    className="win-button h-8 px-3 text-xs"
                  >
                    重新生成
                  </button>
                </div>
              )}
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
                    <Suspense fallback={null}>
                      <StructuredPayloadView data={agentResult.structured_payload} />
                    </Suspense>
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
