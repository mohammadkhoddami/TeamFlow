import {
  Bold,
  Code,
  Eye,
  Heading2,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
  PenLine,
  Quote,
  Strikethrough,
  Terminal,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { Markdown } from './Markdown'
import { cn } from '../lib/utils'

function ToolbarButton({
  title,
  onClick,
  disabled,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      // Keep the textarea selection: don't steal focus on click.
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      className="rounded p-1.5 text-slate-500 transition-colors hover:bg-slate-200/70 hover:text-slate-700 disabled:pointer-events-none disabled:opacity-40"
    >
      {children}
    </button>
  )
}

export function MarkdownEditor({
  value,
  onChange,
  placeholder = 'Write a description…',
  maxLength = 20_000,
  minRows = 5,
  autoFocus = false,
  disabled = false,
  className,
  id,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  maxLength?: number
  minRows?: number
  autoFocus?: boolean
  disabled?: boolean
  className?: string
  id?: string
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [tab, setTab] = useState<'write' | 'preview'>('write')

  const selection = () => {
    const textarea = textareaRef.current
    return {
      start: textarea ? textarea.selectionStart : value.length,
      end: textarea ? textarea.selectionEnd : value.length,
    }
  }

  const focusSelection = (start: number, end: number) => {
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current
      if (!textarea) return
      textarea.focus()
      textarea.setSelectionRange(start, end)
    })
  }

  const applyWrap = (before: string, after: string, fallback: string) => {
    const { start, end } = selection()
    const selected = value.slice(start, end) || fallback
    onChange(`${value.slice(0, start)}${before}${selected}${after}${value.slice(end)}`)
    setTab('write')
    focusSelection(start + before.length, start + before.length + selected.length)
  }

  const applyLink = () => {
    const { start, end } = selection()
    const selected = value.slice(start, end) || 'link text'
    const url = 'https://'
    onChange(`${value.slice(0, start)}[${selected}](${url})${value.slice(end)}`)
    setTab('write')
    focusSelection(start + selected.length + 3, start + selected.length + 3 + url.length)
  }

  const selectedLineRange = () => {
    const { start, end } = selection()
    const lineStart = value.lastIndexOf('\n', Math.max(start - 1, 0)) + 1
    const nextBreak = value.indexOf('\n', end)
    const lineEnd = nextBreak === -1 ? value.length : nextBreak
    return { lineStart, lineEnd }
  }

  const replaceLineBlock = (transform: (line: string, index: number) => string) => {
    const { lineStart, lineEnd } = selectedLineRange()
    const lines = value.slice(lineStart, lineEnd).split('\n')
    const nextBlock = lines.map((line, index) => transform(line, index)).join('\n')
    onChange(`${value.slice(0, lineStart)}${nextBlock}${value.slice(lineEnd)}`)
    setTab('write')
    focusSelection(lineStart, lineStart + nextBlock.length)
  }

  const applyLinePrefix = (prefix: string) => {
    const { lineStart, lineEnd } = selectedLineRange()
    const lines = value.slice(lineStart, lineEnd).split('\n')
    const allPrefixed = lines.every((line) => !line.trim() || line.startsWith(prefix))
    replaceLineBlock((line) => {
      if (!line.trim()) return line
      return allPrefixed ? line.slice(prefix.length) : `${prefix}${line}`
    })
  }

  const applyOrderedList = () => {
    const { lineStart, lineEnd } = selectedLineRange()
    const lines = value.slice(lineStart, lineEnd).split('\n')
    const allNumbered = lines.every((line) => !line.trim() || /^\d+[.)]\s/.test(line))
    replaceLineBlock((line, index) => {
      if (!line.trim()) return line
      if (allNumbered) return line.replace(/^\d+[.)]\s+/, '')
      return `${index + 1}. ${line.replace(/^\s*[-*+]\s+/, '')}`
    })
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Tab') {
      event.preventDefault()
      const { start, end } = selection()
      onChange(`${value.slice(0, start)}  ${value.slice(end)}`)
      focusSelection(start + 2, start + 2)
      return
    }
    const meta = event.metaKey || event.ctrlKey
    if (!meta) return
    const key = event.key.toLowerCase()
    if (key === 'b') {
      event.preventDefault()
      applyWrap('**', '**', 'bold text')
    } else if (key === 'i') {
      event.preventDefault()
      applyWrap('*', '*', 'italic text')
    } else if (key === 'e') {
      event.preventDefault()
      applyWrap('`', '`', 'code')
    } else if (key === 'k') {
      event.preventDefault()
      applyLink()
    }
  }

  const toolbarDisabled = disabled || tab === 'preview'

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-500/20',
        disabled && 'bg-slate-50',
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-1 border-b border-slate-200 bg-slate-50 px-1.5 py-1">
        <div className="flex flex-wrap items-center gap-0.5">
          <ToolbarButton
            title="Bold (Ctrl+B)"
            disabled={toolbarDisabled}
            onClick={() => applyWrap('**', '**', 'bold text')}
          >
            <Bold className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Italic (Ctrl+I)"
            disabled={toolbarDisabled}
            onClick={() => applyWrap('*', '*', 'italic text')}
          >
            <Italic className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Strikethrough"
            disabled={toolbarDisabled}
            onClick={() => applyWrap('~~', '~~', 'strikethrough')}
          >
            <Strikethrough className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Inline code (Ctrl+E)"
            disabled={toolbarDisabled}
            onClick={() => applyWrap('`', '`', 'code')}
          >
            <Code className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Link (Ctrl+K)"
            disabled={toolbarDisabled}
            onClick={applyLink}
          >
            <LinkIcon className="h-3.5 w-3.5" />
          </ToolbarButton>
          <span className="mx-0.5 h-4 w-px bg-slate-200" />
          <ToolbarButton
            title="Heading"
            disabled={toolbarDisabled}
            onClick={() => applyLinePrefix('## ')}
          >
            <Heading2 className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Bulleted list"
            disabled={toolbarDisabled}
            onClick={() => applyLinePrefix('- ')}
          >
            <List className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Numbered list"
            disabled={toolbarDisabled}
            onClick={applyOrderedList}
          >
            <ListOrdered className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Quote"
            disabled={toolbarDisabled}
            onClick={() => applyLinePrefix('> ')}
          >
            <Quote className="h-3.5 w-3.5" />
          </ToolbarButton>
          <ToolbarButton
            title="Code block"
            disabled={toolbarDisabled}
            onClick={() => applyWrap('\n```\n', '\n```', 'code')}
          >
            <Terminal className="h-3.5 w-3.5" />
          </ToolbarButton>
        </div>

        <div className="flex items-center gap-0.5 rounded-md bg-white p-0.5 ring-1 ring-slate-200">
          <button
            type="button"
            onClick={() => setTab('write')}
            className={cn(
              'inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors',
              tab === 'write' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700',
            )}
          >
            <PenLine className="h-3 w-3" /> Write
          </button>
          <button
            type="button"
            onClick={() => setTab('preview')}
            className={cn(
              'inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors',
              tab === 'preview' ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700',
            )}
          >
            <Eye className="h-3 w-3" /> Preview
          </button>
        </div>
      </div>

      {tab === 'preview' ? (
        <div className="min-h-24 px-3 py-2">
          <Markdown text={value} emptyText="Nothing to preview yet" />
        </div>
      ) : (
        <textarea
          id={id}
          ref={textareaRef}
          className="w-full resize-y bg-transparent px-3 py-2 text-sm leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none disabled:text-slate-500"
          rows={minRows}
          value={value}
          maxLength={maxLength}
          placeholder={placeholder}
          autoFocus={autoFocus}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
        />
      )}

      <div className="flex items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 px-2 py-1 text-[10px] text-slate-400">
        <span className="hidden sm:inline">
          Markdown: **bold**, *italic*, `code`, [link](url), lists
        </span>
        <span className={cn(value.length > maxLength * 0.9 && 'font-medium text-amber-600')}>
          {value.length.toLocaleString()}/{maxLength.toLocaleString()}
        </span>
      </div>
    </div>
  )
}
