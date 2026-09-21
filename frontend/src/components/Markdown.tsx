import { Square, SquareCheck } from 'lucide-react'
import { Fragment, createElement, useMemo } from 'react'

import type { InlineToken, MarkdownBlock } from '../lib/markdown'
import { parseInline, parseMarkdown } from '../lib/markdown'
import { cn } from '../lib/utils'

function renderInline(token: InlineToken, key: number): React.ReactNode {
  switch (token.kind) {
    case 'text':
      return <Fragment key={key}>{token.text}</Fragment>
    case 'strong':
      return (
        <strong key={key} className="font-semibold text-slate-900">
          {token.text}
        </strong>
      )
    case 'em':
      return <em key={key}>{token.text}</em>
    case 'strike':
      return <del key={key}>{token.text}</del>
    case 'code':
      return (
        <code
          key={key}
          className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-700"
        >
          {token.text}
        </code>
      )
    case 'link':
      return (
        <a
          key={key}
          href={token.href}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-brand-600 underline decoration-brand-200 underline-offset-2 hover:decoration-brand-500"
        >
          {token.text}
        </a>
      )
  }
}

function Inline({ text }: { text: string }) {
  const tokens = useMemo(() => parseInline(text), [text])
  return <>{tokens.map((token, index) => renderInline(token, index))}</>
}

const HEADING_CLASSES: Record<number, string> = {
  1: 'text-lg font-semibold text-slate-900',
  2: 'text-base font-semibold text-slate-900',
  3: 'text-sm font-semibold text-slate-900',
  4: 'text-sm font-semibold text-slate-700',
  5: 'text-xs font-semibold uppercase tracking-wide text-slate-600',
  6: 'text-xs font-semibold uppercase tracking-wide text-slate-500',
}

function renderBlock(block: MarkdownBlock, key: number): React.ReactNode {
  switch (block.kind) {
    case 'heading': {
      const level = Math.min(Math.max(block.level, 1), 6)
      return createElement(
        `h${level}`,
        { key, className: HEADING_CLASSES[level] },
        <Inline text={block.text} />,
      )
    }
    case 'paragraph':
      return (
        <p key={key} className="whitespace-pre-wrap leading-relaxed">
          <Inline text={block.text} />
        </p>
      )
    case 'code':
      return (
        <div key={key} className="space-y-1">
          {block.language && (
            <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
              {block.language}
            </p>
          )}
          <pre className="overflow-x-auto rounded-lg bg-slate-900 px-3 py-2.5 text-xs leading-relaxed text-slate-100">
            <code className="font-mono">{block.code}</code>
          </pre>
        </div>
      )
    case 'quote':
      return (
        <blockquote
          key={key}
          className="border-l-2 border-slate-300 pl-3 text-slate-500 italic"
        >
          <span className="whitespace-pre-wrap">
            <Inline text={block.text} />
          </span>
        </blockquote>
      )
    case 'list':
      return createElement(
        block.ordered ? 'ol' : 'ul',
        {
          key,
          className: cn(
            'space-y-0.5 pl-5',
            block.ordered ? 'list-decimal' : 'list-disc',
          ),
        },
        block.items.map((item, index) => (
          <li key={index} className="whitespace-pre-wrap leading-relaxed">
            <Inline text={item} />
          </li>
        )),
      )
    case 'taskList':
      return (
        <ul key={key} className="space-y-1">
          {block.items.map((item, index) => (
            <li key={index} className="flex items-start gap-1.5">
              {item.checked ? (
                <SquareCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
              ) : (
                <Square className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-300" />
              )}
              <span
                className={cn(
                  'whitespace-pre-wrap leading-relaxed',
                  item.checked && 'text-slate-400 line-through',
                )}
              >
                <Inline text={item.text} />
              </span>
            </li>
          ))}
        </ul>
      )
    case 'divider':
      return <hr key={key} className="border-slate-200" />
  }
}

export function Markdown({
  text,
  className,
  emptyText = 'No description',
}: {
  text: string | null | undefined
  className?: string
  emptyText?: string
}) {
  const blocks = useMemo(() => parseMarkdown(text ?? ''), [text])

  if (blocks.length === 0) {
    return emptyText ? (
      <p className={cn('text-sm text-slate-400', className)}>{emptyText}</p>
    ) : null
  }

  return (
    <div className={cn('space-y-2 text-sm text-slate-700', className)}>
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  )
}
