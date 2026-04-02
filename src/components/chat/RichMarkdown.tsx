import { Children, Fragment, cloneElement, isValidElement, memo, useDeferredValue, type CSSProperties, type ReactNode } from 'react';
import clsx from 'clsx';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';

type TableAlignment = 'left' | 'center' | 'right';

interface Props {
  content: string;
  streaming?: boolean;
}

const IS_LEGACY_BROWSER = (() => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined' || typeof document === 'undefined') {
    return false;
  }
  const doc = document as Document & { documentMode?: number };
  return Boolean(doc.documentMode) || /MSIE|Trident/i.test(navigator.userAgent);
})();

type HtmlElementNode = {
  type: 'element';
  tagName: string;
  properties?: Record<string, unknown>;
};

const INLINE_MARKER_RE = /\[\[\s*([^\]:\uFF1A]+?)\s*[:\uFF1A]\s*([\s\S]+?)\s*\]\]/g;
const CSS_NAMED_COLOR_RE = /^[a-z]{3,20}$/i;

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

const SANITIZE_SCHEMA: any = {
  ...defaultSchema,
  tagNames: Array.from(new Set([
    ...(defaultSchema.tagNames ?? []),
    'span',
    'mark',
    'sub',
    'sup',
    'kbd',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
  ])),
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    span: [...((defaultSchema.attributes as Record<string, unknown[]>)?.span ?? []), 'data-md-color'],
    th: [...((defaultSchema.attributes as Record<string, unknown[]>)?.th ?? []), 'align'],
    td: [...((defaultSchema.attributes as Record<string, unknown[]>)?.td ?? []), 'align'],
  },
};

function resolveHighlightTone(label: string): 'good' | 'bad' | 'warn' | 'info' | null {
  return HIGHLIGHT_TONE_MAP[label.trim().toLowerCase()] ?? null;
}

function normalizeMarkdownSource(content: string): string {
  return content
    .replace(/\r\n?/g, '\n')
    .replace(/\u00a0/g, ' ')
    .trim();
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function sanitizeHref(href: string): string | null {
  const normalized = href.trim();
  if (!normalized) return null;
  if (/^(https?:|mailto:)/i.test(normalized)) {
    return normalized.replace(/"/g, '%22');
  }
  return null;
}

function renderLegacyMarkdownHtml(content: string): string {
  const normalized = normalizeMarkdownSource(content);
  if (!normalized) return '';

  let html = escapeHtml(normalized);

  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([\s\S]+?)__/g, '<strong>$1</strong>');
  html = html.replace(/(^|[\s(])\*([^*\n][\s\S]*?)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
  html = html.replace(/(^|[\s(])_([^_\n][\s\S]*?)_(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
  html = html.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (_match, label: string, href: string) => {
    const safeHref = sanitizeHref(href);
    return safeHref
      ? `<a href="${safeHref}" target="_blank" rel="noreferrer">${label}</a>`
      : label;
  });
  html = html.replace(/^###\s+(.+)$/gm, '<strong>$1</strong>');
  html = html.replace(/^##\s+(.+)$/gm, '<strong>$1</strong>');
  html = html.replace(/^#\s+(.+)$/gm, '<strong>$1</strong>');
  html = html.replace(/\n/g, '<br />');

  return html;
}

function normalizeColorValue(value: string): string | null {
  const normalized = value.trim().replace(/^["']|["']$/g, '');
  if (!normalized) return null;

  if (/^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(normalized)) {
    return normalized;
  }

  if (/^(?:rgb|hsl)a?\([^()]+\)$/i.test(normalized)) {
    return normalized;
  }

  if (/^var\(--[\w-]+\)$/i.test(normalized)) {
    return normalized;
  }

  if (CSS_NAMED_COLOR_RE.test(normalized)) {
    return normalized.toLowerCase();
  }

  return null;
}

function extractColorFromStyle(styleValue: unknown): string | null {
  const styleText = Array.isArray(styleValue)
    ? styleValue.join(';')
    : typeof styleValue === 'string'
      ? styleValue
      : '';

  if (!styleText) return null;

  const match = styleText.match(/(?:^|;)\s*color\s*:\s*([^;]+)/i);
  if (!match?.[1]) return null;

  return normalizeColorValue(match[1]);
}

function rehypeNormalizeInlineColors() {
  return (tree: unknown) => {
    visit(tree as any, 'element', (node: HtmlElementNode) => {
      const properties = node.properties ?? {};
      const directColor = typeof properties.color === 'string'
        ? normalizeColorValue(properties.color)
        : null;
      const styleColor = extractColorFromStyle(properties.style);
      const color = directColor ?? styleColor;

      if (node.tagName === 'font') {
        node.tagName = 'span';
      }

      if (color) {
        properties['data-md-color'] = color;
      }

      delete properties.color;
      delete properties.style;
      node.properties = properties;
    });
  };
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

function getCellAlignment(node: unknown): TableAlignment | undefined {
  const align = (node as { properties?: Record<string, unknown> } | undefined)?.properties?.align;
  if (align === 'center' || align === 'right' || align === 'left') {
    return align;
  }
  return undefined;
}

function alignmentClass(align: TableAlignment | undefined): string {
  if (align === 'center') return 'text-center';
  if (align === 'right') return 'text-right';
  return 'text-left';
}

function getNodeInlineColor(node: unknown): string | null {
  const color = (node as { properties?: Record<string, unknown> } | undefined)?.properties?.['data-md-color'];
  return typeof color === 'string' ? color : null;
}

function createMarkdownComponents(options?: { compact?: boolean }): Components {
  const compact = options?.compact ?? false;

  return {
    p: ({ children }) => (
      <p className={clsx(compact ? 'my-0 leading-6' : 'my-2 leading-7')}>
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
      <li className="leading-7">
        {decorateMarkdownChildren(children, compact ? 'li-compact' : 'li')}
      </li>
    ),
    strong: ({ children }) => (
      <strong className="font-semibold text-slate-900 dark:text-slate-50">
        {decorateMarkdownChildren(children, compact ? 'strong-compact' : 'strong')}
      </strong>
    ),
    em: ({ children }) => (
      <em className="markdown-emphasis">
        {decorateMarkdownChildren(children, compact ? 'em-compact' : 'em')}
      </em>
    ),
    br: () => <br className="markdown-soft-break" />,
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
    span: ({ node, children }) => {
      const color = getNodeInlineColor(node);
      const style: CSSProperties | undefined = color ? { color } : undefined;

      return (
        <span style={style}>
          {decorateMarkdownChildren(children, compact ? 'span-compact' : 'span')}
        </span>
      );
    },
    table: ({ children }) => (
      <div className="markdown-table-shell my-4 overflow-x-auto rounded-xl border border-surface-divider bg-white shadow-sm dark:border-dark-divider dark:bg-dark-card">
        <table className="markdown-table min-w-full border-separate border-spacing-0 text-left text-[13px] leading-6">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-slate-50/90 dark:bg-slate-900/60">
        {children}
      </thead>
    ),
    tbody: ({ children }) => (
      <tbody>{children}</tbody>
    ),
    tr: ({ children }) => (
      <tr className="odd:bg-white even:bg-slate-50/55 hover:bg-primary/5 dark:odd:bg-dark-card dark:even:bg-dark-sidebar/45 dark:hover:bg-primary/8">
        {children}
      </tr>
    ),
    th: ({ node, children }) => (
      <th
        className={clsx(
          'border-b border-surface-divider px-4 py-3 font-semibold text-slate-700 dark:border-dark-divider dark:text-slate-100',
          alignmentClass(getCellAlignment(node)),
        )}
      >
        {decorateMarkdownChildren(children, compact ? 'th-compact' : 'th')}
      </th>
    ),
    td: ({ node, children }) => (
      <td
        className={clsx(
          'border-t border-surface-divider px-4 py-3 align-top text-text-primary dark:border-dark-divider dark:text-text-dark-primary',
          alignmentClass(getCellAlignment(node)),
        )}
      >
        {decorateMarkdownChildren(children, compact ? 'td-compact' : 'td')}
      </td>
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

const DEFAULT_MARKDOWN_COMPONENTS = createMarkdownComponents();

function RichMarkdown({ content, streaming = false }: Props) {
  const deferredContent = useDeferredValue(streaming ? content : '');
  const sourceContent = streaming ? (deferredContent || content) : content;
  const normalizedContent = normalizeMarkdownSource(sourceContent);

  if (IS_LEGACY_BROWSER) {
    return (
      <div
        className="markdown-body text-[13px] leading-6"
        dangerouslySetInnerHTML={{ __html: renderLegacyMarkdownHtml(normalizedContent) }}
      />
    );
  }

  return (
    <div className="markdown-body text-[13px] leading-6">
      <ReactMarkdown
        components={DEFAULT_MARKDOWN_COMPONENTS}
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={[rehypeRaw, rehypeNormalizeInlineColors, [rehypeSanitize, SANITIZE_SCHEMA]]}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}

export default memo(RichMarkdown);
