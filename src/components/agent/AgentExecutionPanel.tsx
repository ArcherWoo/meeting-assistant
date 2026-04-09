/**
 * AgentExecutionPanel — 端到端 Agent 执行面板
 * 生命周期：matching → ready (参数表单) → executing (SSE步骤流) → completed / error / cancelled
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import { agentMatch, agentExecute, cancelAgentRun, getAgentRun, listKnowledgeImports, uploadFile } from '@/services/api';
import type { AgentMatchResult, AgentFinalResult, AgentExecutionEvent, AgentRunRecord, AgentRunStep, SkillParam, MessageMetadata } from '@/types';
import { buildAgentWriteBackPayload } from '@/utils/agentResult';
import { hasInvalidatedResource, subscribeAppDataInvalidation } from '@/utils/appInvalidation';

// ─── Types ───────────────────────────────────────────────────────────────────

type Phase = 'matching' | 'ready' | 'executing' | 'completed' | 'error' | 'cancelled';

interface StepState {
  index: number;
  stepKey: string;
  description: string;
  status: 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';
  toolName?: string;
  result?: string;
  error?: string;
}

interface KnowledgeImport { id: string; file_name: string; import_status: string }

interface Props {
  query: string;
  conversationId: string;
  onComplete: (payload: { content: string; metadata?: MessageMetadata }) => Promise<void> | void;
  onCancel: () => void;
}

interface PanelUIProps {
  phase: Phase;
  matchResult: AgentMatchResult | null;
  paramValues: Record<string, string>;
  steps: StepState[];
  finalResult: AgentFinalResult | null;
  errorMsg: string | null;
  knowledgeImports: KnowledgeImport[];
  isStopping: boolean;
  isFinalizing: boolean;
  uploadingParamName: string | null;
  stepsEndRef: React.RefObject<HTMLDivElement>;
  onParamChange: (name: string, val: string) => void;
  onParamUpload: (name: string, file: File) => void;
  onExecute: () => void;
  onStop: () => void;
  onCancel: () => void;
  onFinalize: () => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function genRunId() { return `run-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`; }

function StepIcon({ status }: { status: StepState['status'] }) {
  if (status === 'running') return <span className="animate-spin inline-block text-blue-500">⚙</span>;
  if (status === 'completed') return <span className="text-emerald-500">✓</span>;
  if (status === 'failed') return <span className="text-red-500">✕</span>;
  return <span className="text-text-secondary">○</span>;
}

function mapRunStep(step: AgentRunStep): StepState {
  return {
    index: step.index,
    stepKey: step.step_key,
    description: step.description,
    status: step.status === 'pending' ? 'running' : step.status,
    toolName: step.toolName,
    result: step.result,
    error: step.error,
  };
}

function upsertStep(previous: StepState[], next: StepState): StepState[] {
  const index = previous.findIndex((item) => item.index === next.index);
  if (index === -1) {
    return [...previous, next].sort((a, b) => a.index - b.index);
  }
  return previous.map((item) => (item.index === next.index ? { ...item, ...next } : item));
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function AgentExecutionPanel({ query, conversationId, onComplete, onCancel }: Props) {
  const { currentRoleId, llmConfigs, activeLLMConfigId } = useAppStore();
  const activeLLMConfig = llmConfigs.find((c) => c.id === activeLLMConfigId) ?? llmConfigs[0];
  const hasUsableLLMConfig = Boolean(activeLLMConfig && (activeLLMConfig.hasApiKey ?? activeLLMConfig.apiKey));

  const [phase, setPhase] = useState<Phase>('matching');
  const [matchResult, setMatchResult] = useState<AgentMatchResult | null>(null);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [steps, setSteps] = useState<StepState[]>([]);
  const [finalResult, setFinalResult] = useState<AgentFinalResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [knowledgeImports, setKnowledgeImports] = useState<KnowledgeImport[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [finalRun, setFinalRun] = useState<AgentRunRecord | null>(null);
  const [isStopping, setIsStopping] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [uploadingParamName, setUploadingParamName] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const stepsEndRef = useRef<HTMLDivElement>(null);
  const finalizedRunKeyRef = useRef<string | null>(null);
  const finalizingRunKeyRef = useRef<string | null>(null);

  const refreshKnowledgeImports = useCallback(async () => {
    const params = matchResult?.parameters ?? [];
    const needsImports = params.some((p) => p.source === 'knowledge_import' || p.type === 'file');
    if (!needsImports) return;
    try {
      const result = await listKnowledgeImports();
      setKnowledgeImports(result.imports.filter((item) => item.import_status === 'completed'));
    } catch {
      // 静默失败，避免影响主流程
    }
  }, [matchResult]);

  useEffect(() => { stepsEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [steps]);
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  const applyRunSnapshot = useCallback((run: AgentRunRecord | null) => {
    if (!run) return;
    setFinalRun(run);
    setRunId(run.runId);
    setSteps(run.steps.map(mapRunStep));
    setFinalResult(run.finalResult ?? null);
    if (run.status === 'completed') {
      setPhase('completed');
      setErrorMsg(null);
    } else if (run.status === 'cancelled') {
      setPhase('cancelled');
      setErrorMsg(run.error || '执行已取消');
    } else if (run.status === 'failed') {
      setPhase('error');
      setErrorMsg(run.error || 'Agent 执行失败');
    }
  }, []);

  const loadRunRecord = useCallback(async (nextRunId: string) => {
    try {
      const run = await getAgentRun(nextRunId);
      applyRunSnapshot(run);
      return run;
    } catch {
      return null;
    }
  }, [applyRunSnapshot]);

  useEffect(() => {
    void refreshKnowledgeImports();
  }, [refreshKnowledgeImports]);

  useEffect(() => subscribeAppDataInvalidation((resources) => {
    if (hasInvalidatedResource(resources, ['knowledge'])) {
      void refreshKnowledgeImports();
    }
  }), [refreshKnowledgeImports]);

  useEffect(() => {
    let cancelled = false;
    agentMatch(query, currentRoleId)
      .then((result) => {
        if (cancelled) return;
        setMatchResult(result);
        const defaults: Record<string, string> = {};
        for (const p of result.parameters ?? []) {
          if (p.default !== undefined) defaults[p.name] = String(p.default);
        }
        setParamValues(defaults);
        setPhase('ready');
      })
      .catch((e: Error) => { if (!cancelled) { setErrorMsg(e.message); setPhase('error'); } });
    return () => { cancelled = true; };
  }, [query, currentRoleId]);

  const handleParamUpload = useCallback(async (name: string, file: File) => {
    setUploadingParamName(name);
    setErrorMsg(null);
    try {
      const result = await uploadFile(file);
      setParamValues((prev) => ({ ...prev, [name]: result.import_id }));
      await refreshKnowledgeImports();
    } catch (error) {
      setErrorMsg((error as Error).message || '文件上传失败');
    } finally {
      setUploadingParamName(null);
    }
  }, [refreshKnowledgeImports]);

  const handleExecute = useCallback(async () => {
    if (!activeLLMConfig || !hasUsableLLMConfig) { setErrorMsg('请先由管理员配置 LLM'); setPhase('error'); return; }
    const rid = genRunId();
    setRunId(rid);
    setSteps([]);
    setFinalResult(null);
    setFinalRun(null);
    setErrorMsg(null);
    setIsStopping(false);
    setIsFinalizing(false);
    finalizedRunKeyRef.current = null;
    finalizingRunKeyRef.current = null;
    setPhase('executing');
    const abort = new AbortController();
    abortRef.current = abort;

    const normalizedParams: Record<string, unknown> = {};
    for (const p of matchResult?.parameters ?? []) {
      const raw = paramValues[p.name] ?? p.default ?? '';
      normalizedParams[p.name] = p.type === 'boolean' ? raw === 'true' : raw;
    }

    await agentExecute(
      currentRoleId, query, matchResult?.skill_id, normalizedParams,
      { apiUrl: activeLLMConfig.apiUrl, apiKey: activeLLMConfig.apiKey, model: activeLLMConfig.model },
      (event: AgentExecutionEvent) => {
        if (event.run_id) {
          setRunId(event.run_id);
        }

        if (event.type === 'execution_start' && event.context?.steps?.length) {
          setSteps(event.context.steps.map((step) => ({
            index: step.index,
            stepKey: step.step_key ?? '',
            description: step.description,
            status: step.status === 'pending' ? 'running' : (step.status as StepState['status']),
            toolName: step.tool_name,
            result: step.result,
            error: step.error,
          })));
          return;
        }

        if (event.type === 'step_start' && event.step_state) {
          const s = event.step_state;
          setSteps((prev) => upsertStep(prev, {
            index: s.index,
            stepKey: s.step_key,
            description: s.description,
            status: 'running',
            toolName: s.tool_name,
          }));
        } else if (event.type === 'step_complete' && event.step_state) {
          const s = event.step_state;
          setSteps((prev) => upsertStep(prev, {
            index: s.index,
            stepKey: s.step_key,
            description: s.description,
            status: 'completed',
            toolName: s.tool_name,
            result: s.result,
          }));
        } else if (event.type === 'step_error' && event.step_state) {
          const s = event.step_state;
          setSteps((prev) => upsertStep(prev, {
            index: s.index,
            stepKey: s.step_key,
            description: s.description,
            status: 'failed',
            toolName: s.tool_name,
            error: s.error,
          }));
        } else if (event.type === 'complete' && event.final_result) {
          setIsStopping(false);
          setFinalResult(event.final_result);
          setPhase('completed');
          if (event.run_id) {
            void loadRunRecord(event.run_id);
          }
        } else if (event.type === 'error') {
          setIsStopping(false);
          setErrorMsg(event.error ?? event.message ?? 'Agent 执行失败');
          setPhase('error');
          if (event.run_id) {
            void loadRunRecord(event.run_id);
          }
        } else if (event.type === 'cancelled') {
          setIsStopping(false);
          setErrorMsg(event.message ?? '执行已取消');
          setPhase('cancelled');
          if (event.run_id) {
            void loadRunRecord(event.run_id);
          }
        }
      },
      (err: string) => {
        setIsStopping(false);
        setErrorMsg(err);
        setPhase('error');
        void loadRunRecord(rid);
      },
      abort.signal,
      { conversationId, runId: rid, llmProfileId: activeLLMConfig.id },
    );
  }, [activeLLMConfig, hasUsableLLMConfig, currentRoleId, query, matchResult, paramValues, conversationId, loadRunRecord]);

  const handleCancel = useCallback(() => {
    onCancel();
  }, [onCancel]);

  const handleStop = useCallback(() => {
    if (!runId || isStopping) return;
    setIsStopping(true);
    cancelAgentRun(runId)
      .catch((error: Error) => {
        setIsStopping(false);
        setErrorMsg(error.message || '取消 Agent 执行失败');
        setPhase('error');
      });
  }, [isStopping, runId]);

  const handleFinalize = useCallback(async () => {
    const persistedRun = runId ? await loadRunRecord(runId) : null;
    const resolvedRunId = persistedRun?.runId ?? finalRun?.runId ?? runId;
    const resolvedResult = persistedRun?.finalResult ?? finalRun?.finalResult ?? finalResult;
    if (!resolvedResult) return;

    const writeBackKey = resolvedRunId ?? `${conversationId}:${resolvedResult.summary}:${resolvedResult.raw_text}`;
    if (finalizedRunKeyRef.current === writeBackKey || finalizingRunKeyRef.current === writeBackKey) {
      return;
    }

    finalizingRunKeyRef.current = writeBackKey;
    setIsFinalizing(true);
    setErrorMsg(null);

    try {
      await onComplete(buildAgentWriteBackPayload(resolvedResult, resolvedRunId ?? undefined));
      finalizedRunKeyRef.current = writeBackKey;
    } catch (error) {
      finalizingRunKeyRef.current = null;
      setErrorMsg((error as Error).message || '保存 Agent 结果失败');
    } finally {
      finalizingRunKeyRef.current = null;
      setIsFinalizing(false);
    }
  }, [conversationId, finalResult, finalRun, loadRunRecord, onComplete, runId]);

  useEffect(() => {
    if (phase !== 'completed') return;
    if (!(finalRun?.finalResult ?? finalResult)) return;
    void handleFinalize();
  }, [phase, finalResult, finalRun, handleFinalize]);

  return (
    <PanelUI
      phase={phase}
      matchResult={matchResult}
      paramValues={paramValues}
      steps={steps}
      finalResult={finalResult}
      errorMsg={errorMsg}
      knowledgeImports={knowledgeImports}
      isStopping={isStopping}
      isFinalizing={isFinalizing}
      uploadingParamName={uploadingParamName}
      stepsEndRef={stepsEndRef}
      onParamChange={(name, val) => setParamValues((prev) => ({ ...prev, [name]: val }))}
      onParamUpload={(name, file) => { void handleParamUpload(name, file); }}
      onExecute={() => { void handleExecute(); }}
      onStop={handleStop}
      onCancel={handleCancel}
      onFinalize={() => { void handleFinalize(); }}
    />
  );
}

// ─── PanelUI ──────────────────────────────────────────────────────────────────

function PanelUI({ phase, matchResult, paramValues, steps, finalResult, errorMsg, knowledgeImports, isStopping, isFinalizing, uploadingParamName, stepsEndRef, onParamChange, onParamUpload, onExecute, onStop, onCancel, onFinalize }: PanelUIProps) {
  const card = 'win-panel my-3 p-4 rounded-lg border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar';

  if (phase === 'matching') return (
    <div className={card}>
      <div className="flex items-center gap-2 text-sm text-text-secondary">
        <span className="animate-spin">⚙</span> 正在匹配任务技能...
      </div>
    </div>
  );

  if (phase === 'error') return (
    <div className={clsx(card, 'border-red-200 dark:border-red-800')}>
      <p className="text-sm font-semibold text-red-600 dark:text-red-400 mb-1">⚠ 执行失败</p>
      <p className="text-xs text-text-secondary">{errorMsg}</p>
      <button onClick={onCancel} className="win-button mt-3 text-xs h-7 px-3">关闭</button>
    </div>
  );

  if (phase === 'cancelled') return (
    <div className={card}>
      <p className="text-sm text-text-secondary">已取消执行。</p>
      <button onClick={onCancel} className="win-button mt-2 text-xs h-7 px-3">关闭</button>
    </div>
  );

  if (phase === 'ready') {
    const params = matchResult?.parameters ?? [];
    return (
      <div className={card}>
        <div className="flex items-start gap-3 mb-4">
          <span className="text-2xl mt-0.5">🎯</span>
          <div>
            <p className="text-sm font-semibold">{matchResult?.matched ? matchResult.skill_name : '通用执行模式'}</p>
            <p className="text-xs text-text-secondary mt-0.5">
              {matchResult?.matched
                ? `匹配置信度: ${matchResult.confidence ?? '—'} · 关键词: ${matchResult.matched_keywords?.join(', ') ?? '—'}`
                : '未匹配到具体技能，将直接执行查询'}
            </p>
          </div>
        </div>
        {params.length > 0 && (
          <div className="space-y-3 mb-4">
            {params.map((p) => (
              <ParamField
                key={p.name}
                param={p}
                value={paramValues[p.name] ?? ''}
                imports={knowledgeImports}
                uploading={uploadingParamName === p.name}
                onChange={(v) => onParamChange(p.name, v)}
                onUpload={(file) => onParamUpload(p.name, file)}
              />
            ))}
          </div>
        )}
        {errorMsg && (
          <p className="mb-3 text-xs text-red-600 dark:text-red-400">{errorMsg}</p>
        )}
        <div className="flex gap-2">
          <button onClick={onExecute} className="win-button-primary h-8 px-4 text-sm">▶ 开始执行</button>
          <button onClick={onCancel} className="win-button h-8 px-3 text-sm">取消</button>
        </div>
      </div>
    );
  }

  if (phase === 'executing') return (
    <div className={card}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold flex items-center gap-2">
          <span className="animate-spin">⚙</span> 执行中...
        </span>
        <button onClick={onStop} disabled={isStopping} className="win-button h-7 px-2 text-xs disabled:opacity-60 disabled:cursor-not-allowed">
          {isStopping ? '停止中...' : '停止'}
        </button>
      </div>
      <div className="space-y-1.5 max-h-64 overflow-y-auto scrollbar-thin pr-1">
        {steps.map((s) => (
          <div key={s.index} className={clsx('flex items-start gap-2 text-xs rounded px-2 py-1.5', s.status === 'running' ? 'bg-blue-50 dark:bg-blue-900/20' : s.status === 'failed' ? 'bg-red-50 dark:bg-red-900/20' : 'bg-surface dark:bg-dark')}>
            <span className="mt-0.5 shrink-0"><StepIcon status={s.status} /></span>
            <div className="min-w-0">
              <span className="font-medium">{s.description}</span>
              {s.toolName && <span className="ml-1 text-text-secondary">({s.toolName})</span>}
              {s.result && <p className="text-text-secondary mt-0.5 line-clamp-2">{s.result}</p>}
              {s.error && <p className="text-red-500 mt-0.5">{s.error}</p>}
            </div>
          </div>
        ))}
        <div ref={stepsEndRef} />
      </div>
    </div>
  );

  if (phase === 'completed' && finalResult) return (
    <div className={clsx(card, 'border-emerald-200 dark:border-emerald-800')}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-emerald-500 text-lg">✓</span>
        <span className="text-sm font-semibold">执行完成</span>
        {finalResult.used_tools.length > 0 && (
          <span className="win-badge text-xs ml-auto">工具: {finalResult.used_tools.join(', ')}</span>
        )}
      </div>
      <p className="text-sm leading-relaxed mb-3 whitespace-pre-wrap">{finalResult.summary || finalResult.raw_text}</p>
      {finalResult.citations.length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-text-secondary mb-1.5">引用来源</p>
          <div className="space-y-1">
            {finalResult.citations.map((c, i) => (
              <div key={i} className="text-xs flex items-start gap-1.5 text-text-secondary">
                <span className="shrink-0 mt-0.5">{c.source_type === 'knowledge' ? '📄' : c.source_type === 'knowhow' ? '📋' : '🔧'}</span>
                <span className="truncate">{c.title ?? c.label} — {c.snippet?.slice(0, 80)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {finalResult.next_actions.length > 0 && (
        <div className="mb-3">
          <p className="text-xs font-semibold text-text-secondary mb-1">后续建议</p>
          <ul className="space-y-0.5 text-xs text-text-secondary list-disc list-inside">
            {finalResult.next_actions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}
      {errorMsg && (
        <p className="mb-3 text-xs text-red-500">自动保存失败：{errorMsg}</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {isFinalizing ? (
          <span className="text-xs text-text-secondary">正在自动保存到对话...</span>
        ) : errorMsg ? (
          <button onClick={onFinalize} className="win-button-primary h-8 px-4 text-sm">重试保存</button>
        ) : (
          <span className="text-xs text-emerald-600 dark:text-emerald-400">已完成，正在写回对话...</span>
        )}
        <button onClick={onCancel} disabled={isFinalizing} className="win-button h-8 px-3 text-sm disabled:opacity-60 disabled:cursor-not-allowed">关闭</button>
      </div>
    </div>
  );

  return null;
}

// ─── ParamField ───────────────────────────────────────────────────────────────

function ParamField({
  param,
  value,
  imports,
  uploading,
  onChange,
  onUpload,
}: {
  param: SkillParam;
  value: string;
  imports: KnowledgeImport[];
  uploading: boolean;
  onChange: (v: string) => void;
  onUpload: (file: File) => void;
}) {
  const cls = 'w-full rounded border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary';
  const label = (
    <label className="block text-xs font-medium mb-1">
      {param.name}{param.required && <span className="text-red-500 ml-0.5">*</span>}
      {param.description && <span className="ml-1 font-normal text-text-secondary">— {param.description}</span>}
    </label>
  );

  if (param.type === 'boolean') return (
    <div>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="true">是</option>
        <option value="false">否</option>
      </select>
    </div>
  );

  if (param.options?.length) return (
    <div>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        {!param.required && <option value="">（不选择）</option>}
        {param.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );

  if (param.source === 'knowledge_import' || param.type === 'file') return (
    <div>{label}
      <div className="space-y-2">
        <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
          <option value="">（请选择已导入文件）</option>
          {imports.map((imp) => <option key={imp.id} value={imp.id}>{imp.file_name}</option>)}
        </select>
        <div className="flex items-center gap-2">
          <label className="win-button inline-flex h-8 cursor-pointer items-center px-3 text-xs">
            {uploading ? '上传中...' : '上传新文件'}
            <input
              type="file"
              accept=".xls,.xlsx,.csv,.tsv"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.currentTarget.value = '';
                if (file) onUpload(file);
              }}
            />
          </label>
          <span className="text-[11px] text-text-secondary">
            上传后会自动导入并选中这份文件
          </span>
        </div>
      </div>
    </div>
  );

  return (
    <div>{label}
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={param.default ?? ''} className={cls} />
    </div>
  );
}
