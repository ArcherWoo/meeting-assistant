import {
  Component,
  Fragment,
  memo,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import clsx from 'clsx';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import 'katex/dist/katex.min.css';

interface Props {
  content: string;
  className?: string;
  streaming?: boolean;
}

type FenceState = {
  char: '`' | '~';
  length: number;
  startLine: number;
};

type StreamingSplit = {
  stable: string;
  live: string;
  liveRenderMode: 'markdown' | 'plain';
};

let mermaidLoader: Promise<typeof import('mermaid').default> | null = null;

async function loadMermaid() {
  if (!mermaidLoader) {
    mermaidLoader = import('mermaid').then((module) => {
      const mermaid = module.default;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'neutral',
        suppressErrorRendering: true,
      });
      return mermaid;
    });
  }

  return mermaidLoader;
}

function countUnescapedInlineTicks(text: string): number {
  let count = 0;

  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== '`') continue;
    if (index > 0 && text[index - 1] === '\\') continue;

    let runLength = 1;
    while (index + runLength < text.length && text[index + runLength] === '`') {
      runLength += 1;
    }

    if (runLength < 3) {
      count += runLength;
    }

    index += runLength - 1;
  }

  return count;
}

function countLikelyInlineDollarMarkers(text: string): number {
  let count = 0;

  for (let index = 0; index < text.length; index += 1) {
    if (text[index] !== '$') continue;
    if (index > 0 && text[index - 1] === '\\') continue;
    if (text[index - 1] === '$' || text[index + 1] === '$') continue;

    const prev = text[index - 1] ?? '';
    const next = text[index + 1] ?? '';
    const prevIsDigit = /\d/.test(prev);
    const nextIsDigit = /\d/.test(next);

    if (prevIsDigit && (nextIsDigit || next === '.' || next === ',')) {
      continue;
    }

    count += 1;
  }

  return count;
}

function hasMathLikeContent(text: string): boolean {
  return /\\[a-zA-Z]+|[_^{}]|[=+\-*/]/.test(text);
}

function isTableSeparatorLine(line: string): boolean {
  const trimmed = line.trim();
  return /^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(trimmed);
}

function isTableRow(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed || isTableSeparatorLine(trimmed)) return false;

  const pipeCount = (trimmed.match(/\|/g) || []).length;
  if (pipeCount < 2) return false;

  return trimmed.startsWith('|') || trimmed.endsWith('|') || pipeCount >= 3;
}

function isBlankLine(line: string): boolean {
  return !line.trim();
}

function isHeadingLine(line: string): boolean {
  return /^\s{0,3}#{1,6}\s+\S/.test(line.trimEnd());
}

function isHorizontalRuleLine(line: string): boolean {
  return /^\s{0,3}(?:-\s*){3,}$|^\s{0,3}(?:\*\s*){3,}$|^\s{0,3}(?:_\s*){3,}$/.test(line);
}

function isBlockquoteLine(line: string): boolean {
  return /^\s{0,3}>/.test(line);
}

function isListItemLine(line: string): boolean {
  return /^\s{0,3}(?:[-*+]|\d+[.)])\s+\S/.test(line);
}

function isIndentedContinuationLine(line: string): boolean {
  return /^\s{2,}\S/.test(line);
}

function findLastNonEmptyLine(lines: string[]): number {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    if (!isBlankLine(lines[index])) {
      return index;
    }
  }

  return -1;
}

function findTrailingBlockStart(lines: string[], endIndex: number): number {
  if (endIndex < 0) return 0;

  const endLine = lines[endIndex];

  if (isTableRow(endLine) || isTableSeparatorLine(endLine)) {
    let start = endIndex;
    while (start > 0) {
      const previousLine = lines[start - 1];
      if (isTableRow(previousLine) || isTableSeparatorLine(previousLine)) {
        start -= 1;
        continue;
      }
      break;
    }
    return start;
  }

  if (isBlockquoteLine(endLine)) {
    let start = endIndex;
    while (start > 0 && isBlockquoteLine(lines[start - 1])) {
      start -= 1;
    }
    return start;
  }

  if (isListItemLine(endLine) || isIndentedContinuationLine(endLine)) {
    let start = endIndex;
    while (start > 0) {
      const previousLine = lines[start - 1];
      if (isBlankLine(previousLine)) break;
      if (isListItemLine(previousLine) || isIndentedContinuationLine(previousLine)) {
        start -= 1;
        continue;
      }
      break;
    }
    return start;
  }

  if (isHeadingLine(endLine) || isHorizontalRuleLine(endLine)) {
    return endIndex;
  }

  let start = endIndex;
  while (start > 0) {
    const previousLine = lines[start - 1];
    if (isBlankLine(previousLine)) break;
    if (
      isHeadingLine(previousLine)
      || isHorizontalRuleLine(previousLine)
      || isBlockquoteLine(previousLine)
      || isListItemLine(previousLine)
      || isTableRow(previousLine)
      || isTableSeparatorLine(previousLine)
    ) {
      break;
    }
    start -= 1;
  }

  return start;
}

function getLiveRenderMode(live: string): StreamingSplit['liveRenderMode'] {
  const liveLooksUnsafe = (
    live.split('\n').some(isTableRow)
    || countUnescapedInlineTicks(live) % 2 !== 0
    || (countLikelyInlineDollarMarkers(live) % 2 !== 0 && hasMathLikeContent(live))
  );

  return liveLooksUnsafe ? 'plain' : 'markdown';
}

function buildTableSeparator(line: string): string {
  const trimmed = line.trim();
  const core = trimmed.replace(/^\|/, '').replace(/\|$/, '');
  const cells = core.split('|').map((cell) => cell.trim()).filter(Boolean);
  if (cells.length <= 1) return '| --- | --- |';
  return `| ${cells.map(() => '---').join(' | ')} |`;
}

function normalizeMarkdown(raw: string): string {
  return String(raw || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\u0000/g, '');
}

function stabilizeMarkdown(raw: string): string {
  const normalized = normalizeMarkdown(raw);
  if (!normalized.trim()) {
    return normalized;
  }

  const sourceLines = normalized.split('\n');
  const outputLines: string[] = [];
  let openFence: FenceState | null = null;
  let openDisplayMath = false;
  let inlineTickCount = 0;
  let inlineDollarCount = 0;

  for (let index = 0; index < sourceLines.length; index += 1) {
    const line = sourceLines[index];
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})(.*)$/);

    if (fenceMatch) {
      const marker = fenceMatch[1];
      const char = marker[0] as '`' | '~';
      const length = marker.length;

      if (!openFence) {
        openFence = { char, length, startLine: index };
      } else if (openFence.char === char && length >= openFence.length) {
        openFence = null;
      }

      outputLines.push(line);
      continue;
    }

    if (!openFence && trimmed === '$$') {
      openDisplayMath = !openDisplayMath;
      outputLines.push(line);
      continue;
    }

    if (!openFence && !openDisplayMath) {
      inlineTickCount += countUnescapedInlineTicks(line);
      inlineDollarCount += countLikelyInlineDollarMarkers(line);

      const nextLine = sourceLines[index + 1] ?? '';
      if (isTableRow(line) && !isTableSeparatorLine(nextLine) && (isTableRow(nextLine) || !nextLine.trim())) {
        outputLines.push(line);
        outputLines.push(buildTableSeparator(line));
        continue;
      }
    }

    outputLines.push(line);
  }

  let stabilized = outputLines.join('\n');

  if (openFence) {
    stabilized = `${stabilized}\n${openFence.char.repeat(openFence.length)}`;
  }

  if (openDisplayMath) {
    stabilized = `${stabilized}\n$$`;
  }

  if (inlineTickCount % 2 !== 0) {
    stabilized = `${stabilized}\``;
  }

  if (inlineDollarCount % 2 !== 0 && hasMathLikeContent(normalized)) {
    stabilized = `${stabilized}$`;
  }

  return stabilized;
}

function splitStreamingMarkdown(raw: string): StreamingSplit {
  const normalized = normalizeMarkdown(raw);
  if (!normalized.trim()) {
    return { stable: normalized, live: '', liveRenderMode: 'markdown' };
  }

  const lines = normalized.split('\n');
  let openFence: FenceState | null = null;
  let openDisplayMath = false;
  let openDisplayMathStart = -1;
  let lastClosedStructuredLine = -1;

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim();
    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})(.*)$/);

    if (fenceMatch) {
      const marker = fenceMatch[1];
      const char = marker[0] as '`' | '~';
      const length = marker.length;

      if (!openFence) {
        openFence = { char, length, startLine: index };
      } else if (openFence.char === char && length >= openFence.length) {
        openFence = null;
        lastClosedStructuredLine = index;
      }
      continue;
    }

    if (!openFence && trimmed === '$$') {
      if (!openDisplayMath) {
        openDisplayMath = true;
        openDisplayMathStart = index;
      } else {
        openDisplayMath = false;
        openDisplayMathStart = -1;
        lastClosedStructuredLine = index;
      }
      continue;
    }
  }

  if (openFence) {
    const stable = lines.slice(0, openFence.startLine).join('\n');
    const live = lines.slice(openFence.startLine).join('\n');
    return { stable, live, liveRenderMode: 'plain' };
  }

  if (openDisplayMath && openDisplayMathStart >= 0) {
    const stable = lines.slice(0, openDisplayMathStart).join('\n');
    const live = lines.slice(openDisplayMathStart).join('\n');
    return { stable, live, liveRenderMode: 'plain' };
  }

  const lastNonEmptyLine = findLastNonEmptyLine(lines);
  if (lastNonEmptyLine < 0) {
    return { stable: normalized, live: '', liveRenderMode: 'markdown' };
  }

  if (lastNonEmptyLine < lines.length - 1 || lastClosedStructuredLine >= lastNonEmptyLine) {
    return { stable: normalized, live: '', liveRenderMode: 'markdown' };
  }

  const trailingBlockStart = findTrailingBlockStart(lines, lastNonEmptyLine);
  if (trailingBlockStart <= 0) {
    return { stable: '', live: normalized, liveRenderMode: getLiveRenderMode(normalized) };
  }

  const stable = lines.slice(0, trailingBlockStart).join('\n');
  const live = lines.slice(trailingBlockStart).join('\n');

  return {
    stable,
    live,
    liveRenderMode: getLiveRenderMode(live),
  };
}

function PlainTextFallback({ content, className }: Props) {
  return (
    <pre
      className={clsx(
        'whitespace-pre-wrap break-words rounded-lg border border-surface-divider/70 bg-surface/70 px-3 py-3 font-sans text-[13px] leading-6 dark:border-dark-divider dark:bg-dark-sidebar/70',
        className,
      )}
    >
      {content}
    </pre>
  );
}

class MarkdownErrorBoundary extends Component<
  { content: string; className?: string; children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  override componentDidUpdate(prevProps: Readonly<{ content: string }>) {
    if (prevProps.content !== this.props.content && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  override render() {
    if (this.state.hasError) {
      return <PlainTextFallback content={this.props.content} className={this.props.className} />;
    }

    return this.props.children;
  }
}

function LatexBlock({ code }: { code: string }) {
  const latexSource = useMemo(() => `$$\n${code}\n$$`, [code]);

  return (
    <div className="my-3 overflow-x-auto rounded-xl border border-surface-divider bg-white/80 px-4 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-sidebar/70">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {latexSource}
      </ReactMarkdown>
    </div>
  );
}

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState('');
  const renderIdRef = useRef(`mermaid-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;

    setSvg('');
    setError('');

    void (async () => {
      try {
        const mermaid = await loadMermaid();
        const renderId = `${renderIdRef.current}-${Date.now().toString(36)}`;
        const result = await mermaid.render(renderId, code);

        if (!cancelled) {
          setSvg(result.svg);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message || 'Mermaid render failed');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div className="my-3">
        <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
          Mermaid render failed. Showing the source instead.
        </div>
        <PlainTextFallback content={code} />
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="markdown-mermaid scrollbar-thin my-3 flex min-h-[120px] items-center justify-center rounded-xl border border-surface-divider bg-white/80 px-4 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-sidebar/70">
        <span className="text-xs text-text-secondary">Rendering Mermaid diagram...</span>
      </div>
    );
  }

  return (
    <div className="markdown-mermaid scrollbar-thin my-3 overflow-x-auto rounded-xl border border-surface-divider bg-white/80 px-4 py-3 shadow-sm dark:border-dark-divider dark:bg-dark-sidebar/70">
      <div dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  );
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
  table: ({ children }) => (
    <div className="markdown-table-wrap scrollbar-thin">
      <table className="markdown-table">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead>{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  th: ({ children }) => <th>{children}</th>,
  td: ({ children }) => <td>{children}</td>,
  hr: () => <hr className="my-4 border-surface-divider dark:border-dark-divider" />,
  pre: ({ children }) => <Fragment>{children}</Fragment>,
  code: ({ className, children }) => {
    const code = String(children).replace(/\n$/, '');
    const match = /language-([\w-]+)/.exec(className || '');
    const language = (match?.[1] || '').toLowerCase();
    const isBlockCode = Boolean(match) || code.includes('\n');

    if (language === 'mermaid') {
      return <MermaidBlock code={code} />;
    }

    if (language === 'math' || language === 'latex' || language === 'katex') {
      return <LatexBlock code={code} />;
    }

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

function MarkdownRenderer({ content, className }: { content: string; className?: string }) {
  const stabilizedContent = useMemo(() => stabilizeMarkdown(content), [content]);

  return (
    <MarkdownErrorBoundary content={content} className={className}>
      <div className={clsx('markdown-body text-[13px] leading-6', className)}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={markdownComponents}
        >
          {stabilizedContent}
        </ReactMarkdown>
      </div>
    </MarkdownErrorBoundary>
  );
}

function SmartMarkdownBase({ content, className, streaming = false }: Props) {
  const deferredContent = useDeferredValue(content);
  const normalizedContent = useMemo(
    () => normalizeMarkdown(deferredContent),
    [deferredContent],
  );
  const streamingSplit = useMemo(
    () => (streaming ? splitStreamingMarkdown(normalizedContent) : null),
    [normalizedContent, streaming],
  );

  if (!streaming || !streamingSplit || !streamingSplit.live.trim()) {
    return <MarkdownRenderer content={normalizedContent} className={className} />;
  }

  const hasStablePart = Boolean(streamingSplit.stable.trim());

  return (
    <div className={clsx('markdown-body text-[13px] leading-6', className)}>
      {hasStablePart ? <MarkdownRenderer content={streamingSplit.stable} /> : null}

      {streamingSplit.liveRenderMode === 'markdown' ? (
        <MarkdownRenderer
          content={streamingSplit.live}
          className={clsx('markdown-live-tail', !hasStablePart && 'mt-0 border-t-0 pt-0')}
        />
      ) : (
        <div className={clsx('markdown-live-tail', !hasStablePart && 'mt-0 border-t-0 pt-0')}>
          <PlainTextFallback
            content={streamingSplit.live}
            className="border-transparent bg-transparent px-0 py-0 dark:bg-transparent"
          />
        </div>
      )}
    </div>
  );
}

const SmartMarkdown = memo(SmartMarkdownBase);

export default SmartMarkdown;
