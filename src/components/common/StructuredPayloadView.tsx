import type { ReactNode } from 'react';

interface Props {
  data: unknown;
  depth?: number;
}

function isPrimitive(value: unknown): value is string | number | boolean | null {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

function formatPrimitive(value: string | number | boolean | null): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function renderPrimitiveChip(value: string | number | boolean | null, index: number): ReactNode {
  return (
    <span
      key={`${formatPrimitive(value)}-${index}`}
      className="win-chip border-surface-divider bg-white/90 text-[11px] dark:border-dark-divider dark:bg-dark-card"
    >
      {formatPrimitive(value)}
    </span>
  );
}

export default function StructuredPayloadView({ data, depth = 0 }: Props) {
  if (isPrimitive(data)) {
    return (
      <div className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-2 text-[12px] leading-5 dark:border-dark-divider dark:bg-dark-card/80">
        {formatPrimitive(data)}
      </div>
    );
  }

  if (Array.isArray(data)) {
    if (data.length === 0) {
      return (
        <div className="rounded-lg border border-dashed border-surface-divider px-3 py-2 text-[11px] text-text-secondary dark:border-dark-divider dark:text-text-dark-secondary">
          空数组
        </div>
      );
    }

    if (data.every(isPrimitive)) {
      return (
        <div className="flex flex-wrap gap-1.5">
          {data.map((item, index) => renderPrimitiveChip(item, index))}
        </div>
      );
    }

    return (
      <div className="space-y-2">
        {data.map((item, index) => (
          <div
            key={`array-item-${index}`}
            className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-3 dark:border-dark-divider dark:bg-dark-card/80"
          >
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
              条目 {index + 1}
            </p>
            <div className="mt-2">
              <StructuredPayloadView data={item} depth={depth + 1} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (typeof data === 'object' && data) {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0) {
      return (
        <div className="rounded-lg border border-dashed border-surface-divider px-3 py-2 text-[11px] text-text-secondary dark:border-dark-divider dark:text-text-dark-secondary">
          空对象
        </div>
      );
    }

    return (
      <div className={depth === 0 ? 'space-y-3' : 'space-y-2'}>
        {entries.map(([key, value]) => (
          <div
            key={key}
            className="rounded-lg border border-surface-divider/70 bg-white/80 px-3 py-3 dark:border-dark-divider dark:bg-dark-card/80"
          >
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-secondary dark:text-text-dark-secondary">
              {key.replace(/_/g, ' ')}
            </p>
            <div className="mt-2">
              <StructuredPayloadView data={value} depth={depth + 1} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <pre className="overflow-x-auto rounded-lg bg-black/5 p-3 text-[11px] leading-5 dark:bg-white/5">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
