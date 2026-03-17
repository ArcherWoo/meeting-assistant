/**
 * Agent 执行面板
 * 展示 Skill 匹配结果和逐步执行进度（SSE 流式）
 */
import { useState, useRef, useEffect } from 'react';
import clsx from 'clsx';
import { agentMatch, agentExecute } from '@/services/api';
import type { AgentMatchResult, AgentExecutionEvent } from '@/types';

/** 执行步骤状态 */
interface StepState {
  index: number;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  result?: string;
  error?: string;
}

type Phase = 'matching' | 'matched' | 'executing' | 'completed' | 'error';

interface Props {
  query: string;
  onComplete?: (result: string) => void;
  onCancel?: () => void;
}

export default function AgentExecutionPanel({ query, onComplete, onCancel }: Props) {
  const [phase, setPhase] = useState<Phase>('matching');
  const [matchResult, setMatchResult] = useState<AgentMatchResult | null>(null);
  const [steps, setSteps] = useState<StepState[]>([]);
  const [finalResult, setFinalResult] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const matchStarted = useRef(false);

  /** 开始匹配 */
  const startMatch = async () => {
    setPhase('matching');
    try {
      const result = await agentMatch(query);
      setMatchResult(result);
      setPhase(result.matched ? 'matched' : 'error');
      if (!result.matched) setErrorMsg(result.message || '未找到匹配的 Skill');
    } catch (e: unknown) {
      setPhase('error');
      setErrorMsg((e as Error).message);
    }
  };

  // 自动开始匹配（仅一次）
  useEffect(() => {
    if (!matchStarted.current) {
      matchStarted.current = true;
      startMatch();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /** 确认执行 */
  const startExecution = async () => {
    if (!matchResult?.skill_id) return;
    setPhase('executing');
    const controller = new AbortController();
    abortRef.current = controller;

    await agentExecute(
      matchResult.skill_id,
      { file: 'uploaded.pptx' },
      (event: AgentExecutionEvent) => {
        if (event.type === 'execution_start' && event.context?.steps) {
          setSteps(event.context.steps.map((s) => ({
            index: s.index, description: s.description, status: 'pending' as const,
          })));
        } else if (event.type === 'step_start') {
          setSteps((prev) => prev.map((s) =>
            s.index === event.step ? { ...s, status: 'running' as const } : s));
        } else if (event.type === 'step_complete') {
          setSteps((prev) => prev.map((s) =>
            s.index === event.step ? { ...s, status: 'completed' as const, result: event.result } : s));
        } else if (event.type === 'step_error') {
          setSteps((prev) => prev.map((s) =>
            s.index === event.step ? { ...s, status: 'failed' as const, error: event.error } : s));
        } else if (event.type === 'complete') {
          setFinalResult(event.context?.result || event.result || '');
          setPhase('completed');
        } else if (event.type === 'error') {
          setErrorMsg(event.message || '执行失败');
          setPhase('error');
        }
      },
      (error) => { setErrorMsg(error); setPhase('error'); },
      controller.signal,
    );
  };

  const handleStop = () => { abortRef.current?.abort(); onCancel?.(); };

  return (
    <div className="p-4 space-y-4 animate-fade-in">
      {phase === 'matching' && (
        <div className="flex items-center gap-3 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-card">
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <div>
            <p className="text-sm font-medium">正在匹配 Skill...</p>
            <p className="text-xs text-text-secondary mt-0.5 truncate max-w-[300px]">"{query}"</p>
          </div>
        </div>
      )}

      {phase === 'matched' && matchResult && (
        <MatchedCard match={matchResult} onConfirm={startExecution} onCancel={onCancel} />
      )}

      {(phase === 'executing' || phase === 'completed') && (
        <StepsProgress steps={steps} onStop={phase === 'executing' ? handleStop : undefined} />
      )}

      {phase === 'completed' && finalResult && (
        <ResultCard result={finalResult} onDone={() => onComplete?.(finalResult)} />
      )}

      {phase === 'error' && (
        <ErrorCard message={errorMsg} onRetry={startMatch} onCancel={onCancel} />
      )}
    </div>
  );
}

/** 匹配成功卡片 */
function MatchedCard({ match, onConfirm, onCancel }: {
  match: AgentMatchResult; onConfirm: () => void; onCancel?: () => void;
}) {
  return (
    <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-card border border-green-200 dark:border-green-800">
      <p className="text-sm font-medium flex items-center gap-1.5">
        <span>✅</span> 匹配到 Skill: {match.skill_name}
      </p>
      <div className="flex items-center gap-2 mt-1.5 text-xs text-text-secondary">
        <span>置信度: {match.confidence}</span>
        {match.matched_keywords && match.matched_keywords.length > 0 && (
          <span>关键词: {match.matched_keywords.join(', ')}</span>
        )}
      </div>
      <div className="flex gap-2 mt-3">
        <button onClick={onConfirm}
          className="px-4 py-1.5 bg-primary text-white text-sm rounded-button hover:bg-primary-600 transition-colors">
          开始执行
        </button>
        <button onClick={onCancel}
          className="px-4 py-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors">
          取消
        </button>
      </div>
    </div>
  );
}

/** 步骤进度列表 */
function StepsProgress({ steps, onStop }: { steps: StepState[]; onStop?: () => void }) {
  const completed = steps.filter((s) => s.status === 'completed').length;
  const total = steps.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="p-4 bg-surface-card dark:bg-dark-card rounded-card shadow-light">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium">执行进度 {completed}/{total}</span>
        {onStop && (
          <button onClick={onStop} className="text-xs text-red-500 hover:text-red-600 transition-colors">
            ⏹ 停止
          </button>
        )}
      </div>
      <div className="w-full h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full mb-4">
        <div className="h-full bg-primary rounded-full transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      <div className="space-y-2">
        {steps.map((step) => (
          <div key={step.index} className={clsx(
            'flex items-start gap-2 p-2 rounded-lg text-sm transition-colors',
            step.status === 'running' && 'bg-blue-50 dark:bg-blue-900/10',
            step.status === 'completed' && 'opacity-80',
            step.status === 'failed' && 'bg-red-50 dark:bg-red-900/10',
          )}>
            <span className="flex-shrink-0 mt-0.5">
              {step.status === 'pending' && <span className="text-text-secondary">○</span>}
              {step.status === 'running' && (
                <span className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin inline-block" />
              )}
              {step.status === 'completed' && <span className="text-green-500">✓</span>}
              {step.status === 'failed' && <span className="text-red-500">✗</span>}
            </span>
            <div className="min-w-0 flex-1">
              <p className={clsx(step.status === 'running' && 'font-medium')}>{step.description}</p>
              {step.result && <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">{step.result}</p>}
              {step.error && <p className="text-xs text-red-500 mt-0.5">{step.error}</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** 执行结果卡片 */
function ResultCard({ result, onDone }: { result: string; onDone?: () => void }) {
  return (
    <div className="p-4 bg-surface-card dark:bg-dark-card rounded-card shadow-light border-l-4 border-green-500">
      <h4 className="text-sm font-medium mb-2 flex items-center gap-1.5">
        <span>📋</span> 执行结果
      </h4>
      <div className="text-sm whitespace-pre-wrap max-h-[300px] overflow-y-auto scrollbar-thin">{result}</div>
      {onDone && (
        <button onClick={onDone}
          className="mt-3 px-4 py-1.5 bg-primary text-white text-sm rounded-button hover:bg-primary-600 transition-colors">
          完成
        </button>
      )}
    </div>
  );
}

/** 错误卡片 */
function ErrorCard({ message, onRetry, onCancel }: {
  message: string; onRetry: () => void; onCancel?: () => void;
}) {
  return (
    <div className="p-4 bg-red-50 dark:bg-red-900/20 rounded-card border border-red-200 dark:border-red-800">
      <p className="text-sm font-medium text-red-600 dark:text-red-400 flex items-center gap-1.5">
        <span>❌</span> {message}
      </p>
      <div className="flex gap-2 mt-3">
        <button onClick={onRetry}
          className="px-4 py-1.5 text-sm bg-red-100 dark:bg-red-900/40 text-red-600 rounded-button hover:bg-red-200 transition-colors">
          重试
        </button>
        {onCancel && (
          <button onClick={onCancel}
            className="px-4 py-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors">
            返回
          </button>
        )}
      </div>
    </div>
  );
}
