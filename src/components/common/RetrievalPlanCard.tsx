import clsx from 'clsx';

import type { RetrievalPlan, RetrievalPlanAction } from '@/types';

interface Props {
  plan?: RetrievalPlan | null;
  className?: string;
  compact?: boolean;
  title?: string;
}

const surfaceTone: Record<RetrievalPlanAction['surface'], string> = {
  knowledge: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
  knowhow: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300',
  skill: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300',
};

const surfaceLabel: Record<RetrievalPlanAction['surface'], string> = {
  knowledge: '知识库',
  knowhow: '规则库',
  skill: '技能库',
};

const strategyTone: Record<RetrievalPlan['strategy'], string> = {
  llm: 'border-primary/20 bg-primary/10 text-primary',
  fallback: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300',
};

const strategyLabel: Record<RetrievalPlan['strategy'], string> = {
  llm: 'LLM 规划',
  fallback: '回退策略',
};

export default function RetrievalPlanCard({
  plan,
  className,
  compact = false,
  title = '检索规划',
}: Props) {
  if (!plan) return null;

  const wrapperClass = compact
    ? 'rounded-lg border border-surface-divider/80 bg-white/80 px-3 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-card/70'
    : 'rounded-xl border border-surface-divider bg-white px-3 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-card';

  return (
    <div className={clsx(wrapperClass, className)}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
          {title}
        </p>
        <span className={clsx('win-badge px-2 py-1 text-[10px]', strategyTone[plan.strategy])}>
          {strategyLabel[plan.strategy]}
        </span>
        <span className="win-badge border-surface-divider bg-surface px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
          {plan.actions.length} 个动作
        </span>
      </div>

      {plan.intent && (
        <p className="mt-2 text-sm font-medium text-text-primary dark:text-text-dark-primary">
          {plan.intent}
        </p>
      )}

      {plan.normalized_query && (
        <div className="mt-2 rounded-lg border border-surface-divider/70 bg-surface/70 px-3 py-2 dark:border-dark-divider dark:bg-dark-sidebar/60">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
            归一化查询
          </p>
          <p className="mt-1 text-[12px] leading-5 text-text-primary dark:text-text-dark-primary">
            {plan.normalized_query}
          </p>
        </div>
      )}

      {plan.actions.length > 0 ? (
        <div className="mt-3 space-y-2">
          {plan.actions.map((action, index) => (
            <div
              key={`${action.surface}-${action.query}-${index}`}
              className="rounded-lg border border-surface-divider/70 bg-surface-card/80 px-3 py-3 dark:border-dark-divider dark:bg-dark-sidebar/50"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className={clsx('win-badge px-2 py-1 text-[10px]', surfaceTone[action.surface])}>
                  {surfaceLabel[action.surface]}
                </span>
                <span className="win-badge border-surface-divider bg-white/90 px-2 py-1 text-[10px] text-text-secondary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-secondary">
                  Top {action.limit}
                </span>
                {action.required && (
                  <span className="win-badge border-red-200 bg-red-50 px-2 py-1 text-[10px] text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300">
                    必需
                  </span>
                )}
              </div>
              <p className="mt-2 text-[12px] font-medium text-text-primary dark:text-text-dark-primary">
                {action.query}
              </p>
              {action.rationale && (
                <p className="mt-1 text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                  {action.rationale}
                </p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
          本轮规划没有触发额外检索动作。
        </p>
      )}

      {plan.notes?.length ? (
        <div className="mt-3 rounded-lg border border-dashed border-surface-divider px-3 py-2 dark:border-dark-divider">
          <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
            说明
          </p>
          <div className="mt-1 space-y-1">
            {plan.notes.map((note, index) => (
              <p key={`${note}-${index}`} className="text-[11px] leading-5 text-text-secondary dark:text-text-dark-secondary">
                {note}
              </p>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
