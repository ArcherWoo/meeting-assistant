/**
 * 右侧上下文面板
 * 显示：最近回答的上下文引用、Skill 列表（含增删改）、知识库统计、Know-how 规则库概览
 */
import { useState, useEffect, useCallback, useMemo, useRef, type ChangeEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore } from '@/stores/chatStore';
import RetrievalPlanCard from '@/components/common/RetrievalPlanCard';
import {
  listSkills, getKnowledgeStats, getKnowhowStats,
  getSkillContent, saveSkill, updateSkill, deleteSkill,
  uploadFiles, listKnowledgeImports, deleteKnowledgeImport,
} from '@/services/api';
import type { ContextCitation, ContextMetadata, Message, SkillMeta, KnowledgeStats, SkillSuggestionEvent } from '@/types';

/** 已导入文件记录 */
interface ImportRecord {
  id: string;
  file_name: string;
  file_size: number;
  slide_count: number;
  import_status: string;
  imported_at: string;
}

function renderContextBadge(label: string, value: number, tone: 'blue' | 'emerald' | 'amber') {
  const toneClassMap = {
    blue: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300',
    amber: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300',
  };

  return (
    <span key={label} className={`win-badge px-2 py-1 text-[10px] ${toneClassMap[tone]}`}>
      {label} {value}
    </span>
  );
}

function renderCitationIcon(sourceType: ContextCitation['source_type']): string {
  if (sourceType === 'knowledge') return '📄';
  if (sourceType === 'knowhow') return '📋';
  return '🛠️';
}

function renderCitationTypeBadge(sourceType: ContextCitation['source_type']): string {
  if (sourceType === 'knowledge') return '知识库';
  if (sourceType === 'knowhow') return 'Know-how';
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
  ] as Array<{ key: ContextCitation['source_type']; label: string; items: ContextCitation[] }>)
    .filter((group) => group.items.length > 0);
}

function areSameCitationSet(left: ContextCitation[], right: ContextCitation[]): boolean {
  if (left.length != right.length) return false;
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

function getMetadataMessage(messages: Message[]): Message | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === 'assistant'
      && (message.metadata?.context || message.metadata?.skillSuggestion)
    ) {
      return message;
    }
  }
  return null;
}

export default function ContextPanel({ width }: { width?: number }) {
  const { toggleContextPanel, activeSurface, currentRoleId, roles } = useAppStore();
  const currentRole = roles.find((r) => r.id === currentRoleId);
  const {
    conversations,
    activeConversationId,
    messagesByConversation,
  } = useChatStore();
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [kbStats, setKbStats] = useState<KnowledgeStats | null>(null);
  const [khStats, setKhStats] = useState<{ total_rules: number; active_rules: number } | null>(null);

  // 知识库导入状态
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [importing, setImporting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const kbFileInputRef = useRef<HTMLInputElement>(null);
  /** 首次数据加载是否完成（避免 khStats 永远卡在"加载中..."） */
  const [statsLoaded, setStatsLoaded] = useState(false);

  // Skill 编辑器状态
  // isNew=true 表示新建 Skill；originalIsBuiltin 记录原始的 is_builtin（便于提示）
  const [editingSkill, setEditingSkill] = useState<{
    id: string; name: string; content: string; is_builtin: boolean; isNew: boolean; originalIsBuiltin: boolean;
  } | null>(null);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [deletingSkillId, setDeletingSkillId] = useState<string | null>(null);

  const modeConversation = useMemo(() => {
    const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId);
    if (activeConversation?.surface === activeSurface && activeConversation?.roleId === currentRoleId) {
      return activeConversation;
    }
    return conversations.find((conversation) => (
      conversation.surface === activeSurface && conversation.roleId === currentRoleId
    )) ?? null;
  }, [conversations, activeConversationId, activeSurface, currentRoleId]);

  const visibleConversationId = modeConversation?.id ?? null;
  const visibleMessages = visibleConversationId ? (messagesByConversation[visibleConversationId] ?? []) : [];
  const latestMetadataMessage = useMemo(
    () => getMetadataMessage(visibleMessages),
    [visibleMessages],
  );
  const latestContext: ContextMetadata | undefined = latestMetadataMessage?.metadata?.context;
  const latestSkillSuggestion: SkillSuggestionEvent | undefined = latestMetadataMessage?.metadata?.skillSuggestion;
  const latestCitations = latestContext?.citations ?? [];
  const latestRetrievedCitations = latestContext?.retrieved_citations?.length
    ? latestContext.retrieved_citations
    : latestCitations;
  const latestGroupedCitations = buildCitationGroups(latestCitations);
  const latestGroupedRetrievedCitations = buildCitationGroups(latestRetrievedCitations);
  const showRetrievedCitations = Boolean(
    latestContext?.truncated
    && latestContext?.retrieved_citations?.length
    && !areSameCitationSet(latestCitations, latestRetrievedCitations),
  );

  /** 刷新所有数据 */
  const refresh = useCallback(async () => {
    try {
      const [s, kb, kh, imp] = await Promise.allSettled([
        listSkills(), getKnowledgeStats(), getKnowhowStats(), listKnowledgeImports(),
      ]);
      if (s.status === 'fulfilled') setSkills(s.value);
      if (kb.status === 'fulfilled') setKbStats(kb.value);
      if (kh.status === 'fulfilled') setKhStats(kh.value);
      if (imp.status === 'fulfilled') setImports(imp.value.imports || []);
    } catch { /* 静默处理 */ } finally {
      // 无论成功/失败均标记首次加载完成，避免永远卡在"加载中..."
      setStatsLoaded(true);
    }
  }, []);

  /** 知识库导入文件 */
  const handleKbImport = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    e.target.value = '';
    setImporting(true);
    try {
      const result = await uploadFiles(files);
      await refresh();
      if (result.errors.length > 0) {
        alert(`以下文件导入失败：\n${result.errors.map((item) => `${item.filename}: ${item.error}`).join('\n')}`);
      }
    } catch (err: any) {
      alert(`导入失败：${err.message || '未知错误'}`);
    } finally {
      setImporting(false);
    }
  };

  /** 删除知识库记录 */
  const handleDeleteImport = async (importId: string, fileName: string) => {
    if (!confirm(`确定要删除「${fileName}」及其所有向量数据吗？`)) return;
    setDeletingId(importId);
    try {
      await deleteKnowledgeImport(importId);
      await refresh();
    } catch (err: any) {
      alert(`删除失败：${err.message || '未知错误'}`);
    } finally {
      setDeletingId(null);
    }
  };

  // 初始加载 + 角色切换时刷新
  useEffect(() => { refresh(); }, [activeSurface, currentRoleId, refresh]);

  // 定时轮询刷新（每 10 秒）
  useEffect(() => {
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  /** 新建 Skill 模板 */
  const NEW_SKILL_TEMPLATE = `# Skill: 新技能名称

## 描述
在此描述该 Skill 的功能和适用场景。

## 触发条件
- 关键词: "关键词1", "关键词2"
- 输入类型: .pptx 文件

## 执行步骤
1. 第一步描述
2. 第二步描述
3. 第三步描述

## 输出格式
在此描述输出格式。
`;

  /** 打开新建 Skill 编辑器 */
  const handleNewSkill = () => {
    setEditingSkill({ id: '', name: '新 Skill', content: NEW_SKILL_TEMPLATE, is_builtin: false, isNew: true, originalIsBuiltin: false });
    setEditContent(NEW_SKILL_TEMPLATE);
    setSaveMsg('');
  };

  /** 点击 Skill 卡片 → 加载内容并打开编辑器 */
  const handleSkillClick = async (skill: SkillMeta) => {
    try {
      const data = await getSkillContent(skill.id);
      setEditingSkill({ id: skill.id, name: skill.name, content: data.content, is_builtin: data.is_builtin, isNew: false, originalIsBuiltin: data.is_builtin });
      setEditContent(data.content);
      setSaveMsg('');
    } catch (err: any) {
      alert(`无法加载 Skill 内容: ${err.message}`);
    }
  };

  /** 保存编辑后的 Skill（新建或更新） */
  const handleSaveSkill = async () => {
    if (!editingSkill) return;
    setSaving(true);
    setSaveMsg('');
    try {
      let result;
      if (editingSkill.isNew) {
        result = await saveSkill(editContent);
      } else {
        result = await updateSkill(editingSkill.id, editContent);
      }
      setSaveMsg(`✅ ${result.message}`);
      await refresh();
      // 新建成功后更新编辑器状态为已保存的 skill
      if (editingSkill.isNew) {
        setEditingSkill((prev) => prev ? { ...prev, id: result.id, name: result.name, isNew: false } : null);
      }
    } catch (err: any) {
      setSaveMsg(`❌ ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  /** 删除 Skill（内置 Skill 写入墓碑标记实现逻辑删除，用户 Skill 直接删除文件） */
  const handleDeleteSkill = async (skill: SkillMeta, e: React.MouseEvent) => {
    e.stopPropagation();
    const builtinNote = skill.is_builtin
      ? '\n（这是内置 Skill，删除后会立即从列表隐藏，不会修改内置源文件）'
      : '';
    if (!confirm(`确定要删除 Skill「${skill.name}」吗？${builtinNote}`)) return;
    setDeletingSkillId(skill.id);
    try {
      await deleteSkill(skill.id);
      await refresh();
    } catch (err: any) {
      alert(`删除失败：${err.message}`);
    } finally {
      setDeletingSkillId(null);
    }
  };

  const panelStyle = width ? { width, minWidth: width, maxWidth: width } : undefined;
  const panelCls = 'flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-[#F7F8FA] dark:bg-dark flex flex-col';

  // ===== 编辑器视图 =====
  if (editingSkill) {
    return (
      <aside className={panelCls} style={panelStyle ?? { width: 300, minWidth: 300, maxWidth: 300 }}>
        <div className="win-toolbar flex h-12 items-center justify-between px-3">
          <button onClick={() => setEditingSkill(null)} className="win-button-subtle h-8 px-2 text-xs">← 返回</button>
          <h3 className="text-sm font-medium truncate flex-1 mx-2">
            {editingSkill.isNew ? '✨ 新建 Skill' : editingSkill.name}
          </h3>
          <button onClick={toggleContextPanel} className="win-icon-button h-8 w-8">✕</button>
        </div>
        <div className="flex-1 flex flex-col gap-3 overflow-hidden p-3">
          {editingSkill.originalIsBuiltin && !editingSkill.isNew && (
            <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
              📋 内置 Skill — 保存后将在用户目录创建自定义版本，不修改内置文件
            </p>
          )}
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 w-full resize-none rounded-lg border border-surface-divider dark:border-dark-divider bg-white p-3 font-mono text-xs leading-6 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20 dark:bg-dark-card"
            spellCheck={false}
            placeholder="按 Skill Markdown 格式编写..."
          />
          {saveMsg && <p className="text-xs text-text-secondary">{saveMsg}</p>}
          <button
            onClick={handleSaveSkill}
            disabled={saving}
            className="win-button-primary h-9 w-full text-sm"
          >
            {saving
              ? '保存中...'
              : editingSkill.isNew
                ? '💾 创建 Skill'
                : editingSkill.originalIsBuiltin
                  ? '💾 保存为自定义版本'
                  : '💾 保存修改'}
          </button>
        </div>
      </aside>
    );
  }

  // ===== 正常列表视图 =====
  return (
    <aside className={panelCls} style={panelStyle ?? { width: 300, minWidth: 300, maxWidth: 300 }}>
      <div className="win-toolbar flex h-12 items-center justify-between px-3">
        <h3 className="text-sm font-medium">上下文与资源</h3>
        <button onClick={toggleContextPanel} className="win-icon-button h-8 w-8">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3.5">
        <div className="space-y-4">
          {/* 当前角色 */}
          <section>
            <h4 className="win-section-title mb-2">当前角色</h4>
            <div className="win-panel-muted px-3 py-3 text-sm font-medium text-primary">
              {currentRole?.icon ?? '💬'} {currentRole?.name ?? currentRoleId}
            </div>
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* 当前上下文 */}
          <section>
            <div className="flex items-center justify-between mb-1">
              <h4 className="win-section-title">当前上下文</h4>
              {latestCitations.length > 0 && (
                <span className="text-[10px] text-text-secondary flex-shrink-0">
                  {latestCitations.length} 条来源
                </span>
              )}
            </div>
            <p className="mb-2 text-[11px] leading-5 text-text-secondary">
              这里只展示最近一次回答或执行实际使用到的引用、检索计划和 Skill 建议。
            </p>

            {latestContext || latestSkillSuggestion ? (
              <div className="space-y-2">
                {latestContext && (
                  <div className="win-panel-muted px-3 py-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {latestContext.knowledge_count
                        ? renderContextBadge('📚 知识库', latestContext.knowledge_count, 'blue')
                        : null}
                      {latestContext.knowhow_count
                        ? renderContextBadge('📋 Know-how', latestContext.knowhow_count, 'emerald')
                        : null}
                      {latestContext.skill_count
                        ? renderContextBadge('🛠️ Skill', latestContext.skill_count, 'amber')
                        : null}
                    </div>
                    {latestContext.summary && (
                      <p className="mt-2 text-[11px] leading-5 text-text-secondary">
                        已参考：{latestContext.summary}
                      </p>
                    )}
                    {latestContext.truncated && (
                      <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-[11px] leading-5 text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                        <p className="font-medium">上下文已按预算裁剪</p>
                        <p className="mt-1">实际注入：{getContextCountSummary(latestContext, 'injected')}</p>
                        <p className="mt-1">原始召回：{latestContext.retrieved_summary || getContextCountSummary(latestContext, 'retrieved')}</p>
                      </div>
                    )}
                  </div>
                )}

                {latestContext?.retrieval_plan && (
                  <RetrievalPlanCard
                    plan={latestContext.retrieval_plan}
                    compact
                    title="最近检索计划"
                  />
                )}

                {latestSkillSuggestion && (
                  <div className="rounded-lg border border-blue-200 bg-blue-50/80 px-3 py-3 text-xs shadow-sm dark:border-blue-800 dark:bg-blue-900/20">
                    <p className="font-medium text-slate-900 dark:text-slate-100">
                      推荐技能：{latestSkillSuggestion.skill_name}
                    </p>
                    <p className="mt-1 text-[11px] leading-5 text-slate-600 dark:text-slate-300">
                      {latestSkillSuggestion.description}
                    </p>
                    <p className="mt-2 text-[10px] text-text-secondary dark:text-text-dark-secondary">
                      匹配度 {Math.round(latestSkillSuggestion.score * 100)}% · 置信度 {latestSkillSuggestion.confidence}
                    </p>
                    {latestSkillSuggestion.matched_keywords?.length ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {latestSkillSuggestion.matched_keywords.map((keyword) => (
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
                )}

                {latestCitations.length > 0 ? (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-surface-divider bg-white/80 px-3 py-2.5 text-[11px] text-text-secondary shadow-sm dark:border-dark-divider dark:bg-dark-card/80 dark:text-text-dark-secondary">
                      <p className="font-medium text-text-primary dark:text-text-dark-primary">已注入回答</p>
                      <p className="mt-1">{latestContext ? getContextCountSummary(latestContext, 'injected') : '无引用来源'}</p>
                    </div>
                    {latestGroupedCitations.map((group) => (
                      <div key={group.key} className="space-y-2">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                          {group.label}
                        </p>
                        <div className="space-y-2">
                          {group.items.map((citation) => (
                            <div
                              key={citation.id}
                              className="rounded-xl border border-surface-divider bg-white px-3 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-card"
                            >
                              <div className="flex items-start gap-3">
                                <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-surface text-sm shadow-sm dark:border-dark-divider dark:bg-dark-sidebar">
                                  <span>{renderCitationIcon(citation.source_type)}</span>
                                </div>
                                <div className="min-w-0 flex-1 space-y-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                                      {renderCitationTypeBadge(citation.source_type)}
                                    </span>
                                    {citation.page ? (
                                      <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                                        P{citation.page}
                                      </span>
                                    ) : null}
                                  </div>

                                  <div>
                                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                      {getCitationSourceHeading(citation)}
                                    </p>
                                    <p className="mt-1 break-all text-[12px] font-semibold text-text-primary dark:text-text-dark-primary">
                                      {getCitationSourceText(citation)}
                                    </p>
                                  </div>

                                  <div>
                                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                      位置
                                    </p>
                                    <p className="mt-1 text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                      {getCitationLocationText(citation)}
                                    </p>
                                  </div>

                                  <div>
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
                        <div className="rounded-lg border border-dashed border-surface-divider bg-white/70 px-3 py-2.5 text-[11px] text-text-secondary shadow-sm dark:border-dark-divider dark:bg-dark-card/60 dark:text-text-dark-secondary">
                          <p className="font-medium text-text-primary dark:text-text-dark-primary">原始召回（未全部注入）</p>
                          <p className="mt-1">
                            {latestContext ? (latestContext.retrieved_summary || getContextCountSummary(latestContext, 'retrieved')) : '无原始召回信息'}
                          </p>
                        </div>
                        {latestGroupedRetrievedCitations.map((group) => (
                          <div key={`retrieved-${group.key}`} className="space-y-2">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                              {group.label}
                            </p>
                            <div className="space-y-2">
                              {group.items.map((citation) => (
                                <div
                                  key={`retrieved-${citation.id}`}
                                  className="rounded-xl border border-dashed border-surface-divider bg-white/70 px-3 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-card/60"
                                >
                                  <div className="flex items-start gap-3">
                                    <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider bg-surface text-sm shadow-sm dark:border-dark-divider dark:bg-dark-sidebar">
                                      <span>{renderCitationIcon(citation.source_type)}</span>
                                    </div>
                                    <div className="min-w-0 flex-1 space-y-2">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                                          {renderCitationTypeBadge(citation.source_type)}
                                        </span>
                                        {citation.page ? (
                                          <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
                                            P{citation.page}
                                          </span>
                                        ) : null}
                                      </div>

                                      <div>
                                        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                          {getCitationSourceHeading(citation)}
                                        </p>
                                        <p className="mt-1 break-all text-[12px] font-semibold text-text-primary dark:text-text-dark-primary">
                                          {getCitationSourceText(citation)}
                                        </p>
                                      </div>

                                      <div>
                                        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
                                          位置
                                        </p>
                                        <p className="mt-1 text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                                          {getCitationLocationText(citation)}
                                        </p>
                                      </div>

                                      <div>
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
                ) : latestContext ? (
                  <p className="rounded-lg border border-dashed border-surface-divider px-3 py-3 text-[11px] leading-5 text-text-secondary dark:border-dark-divider">
                    这条回答带有上下文元数据，但当前没有可展开的 citation 明细。
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-surface-divider px-3 py-3 text-[11px] leading-5 text-text-secondary dark:border-dark-divider">
                {(currentRole?.chat_capabilities?.includes('auto_knowledge') || currentRole?.capabilities?.includes('rag'))
                  ? '发送一条消息后，这里会展示最近一次回答实际使用到的上下文与引用。'
                  : '当前角色未启用 Chat 自动知识检索；切换到支持相关能力的角色并发起对话后，这里会展示当前上下文。'}
              </p>
            )}
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          <section>
            <div className="flex items-center justify-between gap-2">
              <h4 className="win-section-title">资源库</h4>
              <span className="text-[10px] text-text-secondary">全局资源</span>
            </div>
            <p className="mt-1 text-[11px] leading-5 text-text-secondary">
              下面展示的是系统中已有的资源，不代表当前角色已经启用对应的 Chat 自动增强或 Agent 工具权限。
            </p>
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* Skill 资源 */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h4 className="win-section-title">
                Skill 库 ({skills.length})
              </h4>
              <div className="flex items-center gap-1.5">
                <button onClick={refresh} className="win-icon-button h-7 w-7 text-[11px]" title="刷新">↻</button>
                <button
                  onClick={handleNewSkill}
                  className="win-button-primary h-7 px-2.5 text-[11px]"
                >
                  + 新建
                </button>
              </div>
            </div>
            {skills.length === 0 ? (
              <p className="text-xs text-text-secondary text-center py-3">暂无 Skill</p>
            ) : (
              <div className="space-y-1.5">
                {skills.map((skill) => (
                  <div
                    key={skill.id}
                    className="group rounded-lg border border-surface-divider dark:border-dark-divider bg-white px-3 py-2.5 text-xs shadow-sm transition-colors hover:border-primary/30 dark:bg-dark-card"
                  >
                    <div className="flex items-start justify-between gap-1">
                      <p className="font-medium flex-1 min-w-0 truncate">{skill.name}</p>
                      {/* 操作按钮 - hover 时显示 */}
                      <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => handleSkillClick(skill)}
                          className="win-icon-button h-7 w-7 text-[11px]"
                          title="编辑"
                        >
                          ✏️
                        </button>
                        <button
                          onClick={(e) => handleDeleteSkill(skill, e)}
                          disabled={deletingSkillId === skill.id}
                          className="win-icon-button h-7 w-7 text-[11px] disabled:opacity-50"
                          title={skill.is_builtin ? '删除（隐藏内置 Skill）' : '删除'}
                        >
                          {deletingSkillId === skill.id ? '⏳' : '🗑'}
                        </button>
                      </div>
                    </div>
                    <p className="mt-1 line-clamp-2 cursor-pointer text-text-secondary" onClick={() => handleSkillClick(skill)}>{skill.description}</p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {skill.keywords.slice(0, 3).map((kw) => (
                        <span key={kw} className="win-chip text-[10px]">{kw}</span>
                      ))}
                      {skill.is_builtin && (
                        <span className="win-badge border-blue-200 bg-blue-50 text-[10px] text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">内置</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* 知识库资源 */}
          <section>
            <div className="flex items-center justify-between mb-1">
              <h4 className="win-section-title">知识库资源</h4>
              <div className="flex items-center gap-1 flex-shrink-0">
                <input
                  ref={kbFileInputRef}
                  type="file"
                  multiple
                  accept=".ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp"
                  className="hidden"
                  onChange={handleKbImport}
                />
                <button
                  onClick={() => kbFileInputRef.current?.click()}
                  disabled={importing}
                  className="win-button-primary h-7 px-2.5 text-[11px]"
                >
                  {importing ? '导入中...' : '导入文件'}
                </button>
              </div>
            </div>
            <p className="mb-2 text-[11px] leading-5 text-text-secondary">
              导入与管理系统内的知识资源；是否被 Chat/Agent 使用由角色策略决定。
            </p>

            {/* 统计卡片 */}
            {kbStats && (
              <div className="grid grid-cols-2 gap-2 mb-2">
                <StatCard label="文件导入" value={kbStats.total_ppt_imports} />
                <StatCard label="向量块" value={kbStats.total_vector_chunks} />
              </div>
            )}

            {/* 已导入文件列表 */}
            {imports.length > 0 ? (
              <div className="space-y-1 mt-2">
                <p className="text-[10px] text-text-secondary mb-1">已导入文件 ({imports.length})</p>
                {imports.map((imp) => (
                  <div key={imp.id} className="group flex items-center gap-2 rounded-md border border-surface-divider dark:border-dark-divider bg-white px-2.5 py-2 text-xs shadow-sm dark:bg-dark-card">
                    <span className="text-[10px]">📄</span>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-[11px] font-medium">{imp.file_name}</p>
                    </div>
                    <button
                      onClick={() => handleDeleteImport(imp.id, imp.file_name)}
                      disabled={deletingId === imp.id}
                      className="win-icon-button h-7 w-7 flex-shrink-0 text-[11px] opacity-0 transition-all group-hover:opacity-100 disabled:opacity-50"
                      title="删除"
                    >
                      {deletingId === imp.id ? '⏳' : '🗑'}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-secondary text-center py-2">暂无导入文件</p>
            )}
          </section>

          <div className="border-t border-surface-divider dark:border-dark-divider" />

          {/* Know-how 规则库概览 */}
          <section>
            <div className="mb-2">
              <h4 className="win-section-title">Know-how 规则库</h4>
              <p className="mt-1 text-[11px] leading-5 text-text-secondary">
                这里展示全局规则资源概况，不代表当前角色已经开启自动规则检索或主动查询规则库。
              </p>
            </div>
            {!statsLoaded ? (
              <div className="h-10 w-full rounded-md bg-surface-divider/40 animate-pulse dark:bg-dark-divider/40" />
            ) : khStats ? (
              <div className="win-panel-muted px-3 py-3 text-xs text-text-secondary">
                共 {khStats.total_rules} 条规则，{khStats.active_rules} 条启用
              </div>
            ) : (
              <p className="text-xs text-text-secondary text-center py-3">暂无数据</p>
            )}
          </section>
        </div>
      </div>
    </aside>
  );
}

/** 统计数字卡片 */
function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="win-panel-muted px-3 py-3 text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[10px] text-text-secondary">{label}</p>
    </div>
  );
}
