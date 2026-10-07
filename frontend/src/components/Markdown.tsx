import { ImageOff, Square, SquareCheck } from 'lucide-react'
import { Fragment, createElement, useEffect, useMemo, useState } from 'react'

import { attachmentsApi } from '../lib/api'
import type { InlineToken, MarkdownBlock } from '../lib/markdown'
import { parseInline, parseMarkdown } from '../lib/markdown'
import { cn } from '../lib/utils'

// Attachment images resolve their short-lived download URL once per id and
// cache it for the session; `attachment://<uuid>` keeps the markdown portable.
const grantCache = new Map<string, Promise<string | null>>()

function resolveAttachment(id: string): Promise<string | null> {
  const cached = grantCache.get(id)
  if (cached) return cached
  const pending = attachmentsApi
    .downloadUrl(id)
    .then((grant) => grant.download_url)
    .catch(() => null)
  grantCache.set(id, pending)
  return pending
}

function MarkdownImage({
  src,
  alt,
  className,
}: {
  src: string
  alt: string
  className?: string
}) {
  const [resolved, setResolved] = useState<string | null>(
    src.startsWith('attachment://') ? null : src,
  )
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    if (src.startsWith('attachment://')) {
      const id = src.slice('attachment://'.length)
      void resolveAttachment(id).then((url) => {
        if (active) {
          setResolved(url)
          if (!url) setFailed(true)
        }
      })
    } else {
      setResolved(src)
    }
    return () => {
      active = false
    }
  }, [src])

  if (failed || (!resolved && !src.startsWith('attachment://'))) {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-500">
        <ImageOff className="h-3.5 w-3.5" /> {alt || 'image'}
      </span>
    )
  }
  if (!resolved) {
    return (
      <span className="inline-block animate-pulse rounded bg-slate-100 px-6 py-3 text-xs text-slate-400">
        {alt || 'Loading image…'}
      </span>
    )
  }
  return (
    <img
      src={resolved}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      className={cn('max-h-96 max-w-full rounded-lg border border-slate-200', className)}
    />
  )
}

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
    case 'image':
      return <MarkdownImage key={key} src={token.src} alt={token.alt} className="my-1" />
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

const ALIGN_CLASSES = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
} as const

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
    case 'image':
      return <MarkdownImage key={key} src={block.src} alt={block.alt} className="my-1" />
    case 'table':
      return (
        <div key={key} className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200">
                {block.header.map((cell, index) => (
                  <th
                    key={index}
                    className={cn(
                      'px-2 py-1.5 font-semibold text-slate-700',
                      ALIGN_CLASSES[block.align[index] ?? 'left'],
                    )}
                  >
                    <Inline text={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b border-slate-100">
                  {block.header.map((_, cellIndex) => (
                    <td
                      key={cellIndex}
                      className={cn(
                        'px-2 py-1.5 align-top text-slate-600',
                        ALIGN_CLASSES[block.align[cellIndex] ?? 'left'],
                      )}
                    >
                      <Inline text={row[cellIndex] ?? ''} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
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
