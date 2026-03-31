import { Children, Fragment, cloneElement, isValidElement, memo, type ReactNode } from 'react';
import clsx from 'clsx';
import ReactMarkdown, { type Components } from 'react-markdown';

type TableAlignment = 'left' | 'center' | 'right';

interface ParsedTable {
  header: string[];
  alignments: TableAlignment[];
  rows: string[][];
}

type MarkdownBlock =
  | { type: 'markdown'; content: string }
  | { type: 'table'; table: ParsedTable };

interface Props {
  content: string;
}

const INLINE_MARKER_RE = /\[\[\s*([^\]:\uFF1A]+?)\s*[:\uFF1A]\s*([\s\S]+?)\s*\]\]/g;

const HIGHLIGHT_TONE_MAP: Record<string, 'good' | 'bad' | 'warn' | 'info'> = {
  good: 'good',
  ok: 'good',
  success: 'good',
  positive: 'good',
  strength: 'good',
  highlight: 'good',
  plus: 'good',
  '\u597d': 'good',
  '\u4f18\u52bf': 'good',
  '\u4eae\u70b9': 'good',
  '\u6b63\u5411': 'good',
  bad: 'bad',
  risk: 'bad',
  negative: 'bad',
  blocker: 'bad',
  issue: 'bad',
  danger: 'bad',
  '\u574f': 'bad',
  '\u98ce\u9669': 'bad',
  '\u95ee\u9898': 'bad',
  '\u963b\u585e': 'bad',
  warn: 'warn',
  warning: 'warn',
  caution: 'warn',
  attention: 'warn',
  note: 'warn',
  '\u63d0\u9192': 'warn',
  '\u6ce8\u610f': 'warn',
  '\u5173\u6ce8': 'warn',
  info: 'info',
  tip: 'info',
  neutral: 'info',
  '\u4fe1\u606f': 'info',
  '\u8bf4\u660e': 'info',
  '\u63d0\u793a': 'info',
};

function resolveHighlightTone(label: string): 'good' | 'bad' | 'warn' | 'info' | null {
  return HIGHLIGHT_TONE_MAP[label.trim().toLowerCase()] ?? null;
}

function splitMarkdownTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1);

  const cells: string[] = [];
  let current = '';
  let escaped = false;

  for (const char of trimmed) {
    if (escaped) {
      current += char;
      escaped = false;
      continue;
    }

    if (char === '\\') {
      escaped = true;
      continue;
    }

    if (char === '|') {
      cells.push(current.trim());
      current = '';
      continue;
    }

    current += char;
  }

  cells.push(current.trim());
  return cells;
}

function isMarkdownTableSeparator(line: string): boolean {
  const normalized = line.trim();
  return /^\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(normalized);
}

function isMarkdownTableStart(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length) return false;

  const header = lines[index]?.trim();
  const separator = lines[index + 1]?.trim();

  if (!header || !separator) return false;
  if (!header.includes('|')) return false;

  return isMarkdownTableSeparator(separator);
}

function parseAlignmentRow(line: string): TableAlignment[] {
  return splitMarkdownTableRow(line).map((cell) => {
    const normalized = cell.trim();
    const alignLeft = normalized.startsWith(':');
    const alignRight = normalized.endsWith(':');

    if (alignLeft && alignRight) return 'center';
    if (alignRight) return 'right';
    return 'left';
  });
}

function normalizeTableRows(rows: string[][], columnCount: number): string[][] {
  return rows.map((row) => {
    if (row.length === columnCount) return row;
    if (row.length > columnCount) return row.slice(0, columnCount);
    return [...row, ...Array.from({ length: columnCount - row.length }, () => '')];
  });
}

function parseMarkdownTable(lines: string[], startIndex: number): { block: MarkdownBlock; nextIndex: number } {
  const header = splitMarkdownTableRow(lines[startIndex]);
  const alignments = parseAlignmentRow(lines[startIndex + 1]);
  let nextIndex = startIndex + 2;
  const rowLines: string[][] = [];

  while (nextIndex < lines.length) {
    const line = lines[nextIndex];
    if (!line.trim() || !line.includes('|')) break;
    rowLines.push(splitMarkdownTableRow(line));
    nextIndex += 1;
  }

  const columnCount = header.length;

  return {
    block: {
      type: 'table',
      table: {
        header,
        alignments: normalizeTableRows([alignments], columnCount)[0] as TableAlignment[],
        rows: normalizeTableRows(rowLines, columnCount),
      },
    },
    nextIndex,
  };
}

function parseMarkdownBlocks(content: string): MarkdownBlock[] {
  const normalized = content.replace(/\r\n?/g, '\n');
  const lines = normalized.split('\n');
  const blocks: MarkdownBlock[] = [];
  const markdownBuffer: string[] = [];
  let inFence = false;

  const flushMarkdown = () => {
    const segment = markdownBuffer.join('\n').trim();
    markdownBuffer.length = 0;
    if (segment) {
      blocks.push({ type: 'markdown', content: segment });
    }
  };

  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const fenceMatch = /^(```|~~~)/.exec(line.trim());

    if (fenceMatch) {
      inFence = !inFence;
      markdownBuffer.push(line);
      index += 1;
      continue;
    }

    if (!inFence && isMarkdownTableStart(lines, index)) {
      flushMarkdown();
      const parsed = parseMarkdownTable(lines, index);
      blocks.push(parsed.block);
      index = parsed.nextIndex;
      continue;
    }

    markdownBuffer.push(line);
    index += 1;
  }

  flushMarkdown();
  return blocks;
}

function renderAnnotatedText(text: string, keyPrefix: string): ReactNode {
  let lastIndex = 0;
  let matchIndex = 0;
  const nodes: ReactNode[] = [];

  text.replace(INLINE_MARKER_RE, (fullMatch, rawLabel, rawContent, offset: number) => {
    if (offset > lastIndex) {
      nodes.push(text.slice(lastIndex, offset));
    }

    const tone = resolveHighlightTone(String(rawLabel));
    const contentText = String(rawContent).trim();

    if (!tone || !contentText) {
      nodes.push(fullMatch);
    } else {
      nodes.push(
        <span
          key={`${keyPrefix}-${matchIndex}`}
          className={clsx(
            'markdown-highlight markdown-highlight-inline',
            tone === 'good' && 'markdown-highlight-good',
            tone === 'bad' && 'markdown-highlight-bad',
            tone === 'warn' && 'markdown-highlight-warn',
            tone === 'info' && 'markdown-highlight-info',
          )}
        >
          {contentText}
        </span>,
      );
      matchIndex += 1;
    }

    lastIndex = offset + fullMatch.length;
    return fullMatch;
  });

  if (nodes.length === 0) return text;

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

function decorateMarkdownChildren(node: ReactNode, keyPrefix = 'md'): ReactNode {
  if (typeof node === 'string') {
    return renderAnnotatedText(node, keyPrefix);
  }

  if (Array.isArray(node)) {
    return Children.map(node, (child, index) => (
      <Fragment key={`${keyPrefix}-${index}`}>
        {decorateMarkdownChildren(child, `${keyPrefix}-${index}`)}
      </Fragment>
    ));
  }

  if (isValidElement<{ children?: ReactNode }>(node)) {
    if (typeof node.type === 'string' && node.type === 'code') {
      return node;
    }

    const childNodes = node.props.children;
    if (childNodes === undefined) return node;

    return cloneElement(
      node,
      undefined,
      decorateMarkdownChildren(childNodes, `${keyPrefix}-child`),
    );
  }

  return node;
}

function createMarkdownComponents(options?: { compact?: boolean }): Components {
  const compact = options?.compact ?? false;

  return {
    p: ({ children }) => (
      <p className={clsx(compact ? 'my-0 whitespace-pre-wrap' : 'my-2 whitespace-pre-wrap')}>
        {decorateMarkdownChildren(children, compact ? 'p-compact' : 'p')}
      </p>
    ),
    h1: ({ children }) => (
      <h1 className="mt-4 mb-2 text-lg font-semibold">
        {decorateMarkdownChildren(children, 'h1')}
      </h1>
    ),
    h2: ({ children }) => (
      <h2 className="mt-4 mb-2 text-base font-semibold">
        {decorateMarkdownChildren(children, 'h2')}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mt-3 mb-2 text-sm font-semibold">
        {decorateMarkdownChildren(children, 'h3')}
      </h3>
    ),
    ul: ({ children }) => (
      <ul className={clsx(compact ? 'my-1 list-disc space-y-1 pl-4' : 'my-2 list-disc space-y-1 pl-5')}>
        {decorateMarkdownChildren(children, compact ? 'ul-compact' : 'ul')}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className={clsx(compact ? 'my-1 list-decimal space-y-1 pl-4' : 'my-2 list-decimal space-y-1 pl-5')}>
        {decorateMarkdownChildren(children, compact ? 'ol-compact' : 'ol')}
      </ol>
    ),
    li: ({ children }) => (
      <li className="whitespace-pre-wrap">
        {decorateMarkdownChildren(children, compact ? 'li-compact' : 'li')}
      </li>
    ),
    blockquote: ({ children }) => (
      <blockquote className="my-3 border-l-4 border-primary/35 bg-surface/80 px-3 py-2 text-text-secondary dark:bg-dark-sidebar/70 dark:text-text-dark-secondary">
        {decorateMarkdownChildren(children, compact ? 'blockquote-compact' : 'blockquote')}
      </blockquote>
    ),
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-primary underline decoration-primary/35 underline-offset-2 hover:decoration-primary"
      >
        {decorateMarkdownChildren(children, compact ? 'link-compact' : 'link')}
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
}

function renderTableCell(content: string, key: string) {
  if (!content.trim()) return null;

  return (
    <ReactMarkdown components={createMarkdownComponents({ compact: true })} key={key}>
      {content}
    </ReactMarkdown>
  );
}

function alignmentClass(align: TableAlignment | undefined): string {
  if (align === 'center') return 'text-center';
  if (align === 'right') return 'text-right';
  return 'text-left';
}

function MarkdownTable({ table }: { table: ParsedTable }) {
  return (
    <div className="markdown-table-shell my-4 overflow-x-auto rounded-xl border border-surface-divider bg-white shadow-sm dark:border-dark-divider dark:bg-dark-card">
      <table className="markdown-table min-w-full border-separate border-spacing-0 text-left text-[13px] leading-6">
        <thead className="bg-slate-50/90 dark:bg-slate-900/60">
          <tr>
            {table.header.map((cell, index) => (
              <th
                key={`head-${index}`}
                className={clsx(
                  'border-b border-surface-divider px-4 py-3 font-semibold text-slate-700 dark:border-dark-divider dark:text-slate-100',
                  alignmentClass(table.alignments[index]),
                )}
              >
                {renderTableCell(cell, `head-${index}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr
              key={`row-${rowIndex}`}
              className="odd:bg-white even:bg-slate-50/55 hover:bg-primary/5 dark:odd:bg-dark-card dark:even:bg-dark-sidebar/45 dark:hover:bg-primary/8"
            >
              {row.map((cell, cellIndex) => (
                <td
                  key={`row-${rowIndex}-cell-${cellIndex}`}
                  className={clsx(
                    'border-t border-surface-divider px-4 py-3 align-top text-text-primary dark:border-dark-divider dark:text-text-dark-primary',
                    alignmentClass(table.alignments[cellIndex]),
                  )}
                >
                  {renderTableCell(cell, `row-${rowIndex}-cell-${cellIndex}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RichMarkdown({ content }: Props) {
  const blocks = parseMarkdownBlocks(content);
  const markdownComponents = createMarkdownComponents();

  return (
    <div className="markdown-body text-[13px] leading-6">
      {blocks.map((block, index) => (
        block.type === 'table' ? (
          <MarkdownTable key={`table-${index}`} table={block.table} />
        ) : (
          <ReactMarkdown key={`markdown-${index}`} components={markdownComponents}>
            {block.content}
          </ReactMarkdown>
        )
      ))}
    </div>
  );
}

export default memo(RichMarkdown);
