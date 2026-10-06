// Minimal, dependency-free Markdown parser for task descriptions and comments.
// It intentionally supports the Jira/GFM subset people actually use in work
// items: headings, bold/italic/strikethrough, inline code, fenced code blocks,
// links (and bare URLs), ordered/unordered/task lists, blockquotes and rules.
//
// The parser only produces data — `components/Markdown.tsx` renders it as
// React elements, so raw HTML in a description is never interpreted.

export type TableAlignment = 'left' | 'center' | 'right'

export type MarkdownBlock =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; language: string; code: string }
  | { kind: 'quote'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'taskList'; items: { checked: boolean; text: string }[] }
  | { kind: 'divider' }
  | { kind: 'image'; alt: string; src: string }
  | { kind: 'table'; header: string[]; align: TableAlignment[]; rows: string[][] }

export type InlineToken =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; text: string }
  | { kind: 'em'; text: string }
  | { kind: 'strike'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; href: string }
  | { kind: 'image'; alt: string; src: string }

const HEADING = /^(#{1,6})\s+(.*)$/
const FENCE = /^```\s*([\w+#-]*)\s*$/
const DIVIDER = /^(?:-{3,}|\*{3,}|_{3,})\s*$/
const QUOTE_LINE = /^\s*>\s?(.*)$/
const TASK_ITEM = /^\s*[-*+]\s+\[([ xX])\]\s+(.*)$/
const UL_ITEM = /^\s*[-*+]\s+(?!\[[ xX]\]\s)(.*)$/
const OL_ITEM = /^\s*\d+[.)]\s+(.*)$/
const IMAGE_LINE = /^!\[([^\]\n]*)\]\(([^)\s]+)\)$/
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/

function isTableStart(line: string, next: string | undefined): boolean {
  return line.includes('|') && next !== undefined && TABLE_DIVIDER.test(next)
}

function splitTableRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim())
}

function tableAlignments(divider: string): TableAlignment[] {
  return splitTableRow(divider).map((cell) => {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) return 'center'
    if (right) return 'right'
    return 'left'
  })
}

function isBlockStart(line: string): boolean {
  return (
    !line.trim() ||
    FENCE.test(line) ||
    HEADING.test(line) ||
    DIVIDER.test(line) ||
    QUOTE_LINE.test(line) ||
    TASK_ITEM.test(line) ||
    UL_ITEM.test(line) ||
    OL_ITEM.test(line) ||
    IMAGE_LINE.test(line)
  )
}

function gatherItems(
  lines: string[],
  start: number,
  pattern: RegExp,
): { items: string[]; next: number } {
  const items: string[] = []
  let index = start
  while (index < lines.length) {
    const match = pattern.exec(lines[index])
    if (!match) break
    let item = match[1].trim()
    index += 1
    // Indented, non-block continuation lines belong to the current item.
    while (
      index < lines.length &&
      lines[index].trim().length > 0 &&
      /^\s{2,}/.test(lines[index]) &&
      !isBlockStart(lines[index])
    ) {
      item += `\n${lines[index].trim()}`
      index += 1
    }
    items.push(item)
  }
  return { items, next: index }
}

export function parseMarkdown(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    const fence = FENCE.exec(line)
    if (fence) {
      const language = fence[1] ?? ''
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !/^```/.test(lines[index])) {
        codeLines.push(lines[index])
        index += 1
      }
      index += 1 // closing fence (or end of input)
      blocks.push({ kind: 'code', language, code: codeLines.join('\n') })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() })
      index += 1
      continue
    }

    if (DIVIDER.test(line)) {
      blocks.push({ kind: 'divider' })
      index += 1
      continue
    }

    const image = IMAGE_LINE.exec(line)
    if (image) {
      blocks.push({ kind: 'image', alt: image[1], src: image[2] })
      index += 1
      continue
    }

    if (isTableStart(line, lines[index + 1])) {
      const header = splitTableRow(line)
      const align = tableAlignments(lines[index + 1])
      index += 2
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes('|')) {
        rows.push(splitTableRow(lines[index]))
        index += 1
      }
      blocks.push({ kind: 'table', header, align, rows })
      continue
    }

    if (QUOTE_LINE.test(line)) {
      const quoteLines: string[] = []
      while (index < lines.length) {
        const match = QUOTE_LINE.exec(lines[index])
        if (!match) break
        quoteLines.push(match[1])
        index += 1
      }
      blocks.push({ kind: 'quote', text: quoteLines.join('\n') })
      continue
    }

    if (TASK_ITEM.test(line)) {
      const items: { checked: boolean; text: string }[] = []
      while (index < lines.length) {
        const match = TASK_ITEM.exec(lines[index])
        if (!match) break
        items.push({ checked: match[1].toLowerCase() === 'x', text: match[2].trim() })
        index += 1
      }
      blocks.push({ kind: 'taskList', items })
      continue
    }

    if (UL_ITEM.test(line)) {
      const { items, next } = gatherItems(lines, index, UL_ITEM)
      blocks.push({ kind: 'list', ordered: false, items })
      index = next
      continue
    }

    if (OL_ITEM.test(line)) {
      const { items, next } = gatherItems(lines, index, OL_ITEM)
      blocks.push({ kind: 'list', ordered: true, items })
      index = next
      continue
    }

    const paragraphLines: string[] = [line]
    index += 1
    while (index < lines.length && !isBlockStart(lines[index])) {
      paragraphLines.push(lines[index])
      index += 1
    }
    blocks.push({ kind: 'paragraph', text: paragraphLines.join('\n') })
  }

  return blocks
}

// Images must come before links in the alternation: `![alt](src)` starts with
// `[` one character in, so a link-first pattern would tear images apart.
const INLINE_PATTERN =
  /(!\[([^\]\n]*)\]\(([^)\s]+)\))|(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(~~[^~\n]+~~)|(\[[^\]\n]+\]\(([^)\s]+)\))/g

const URL_PATTERN = /https?:\/\/[^\s<>()]+/g

export function isSafeHref(href: string): boolean {
  return /^(https?:\/\/|mailto:|\/|#)/i.test(href)
}

// Inline attachments are addressed by their attachment id; remote images must
// be http(s). Everything else (javascript:, data:, ...) renders as text.
export function isSafeImageSrc(src: string): boolean {
  return /^(https?:\/\/|\/|attachment:\/\/)/i.test(src)
}

function isSafeWordBoundary(source: string, index: number): boolean {
  if (index === 0) return true
  return !/[\w*_~`]/.test(source[index - 1])
}

function pushText(tokens: InlineToken[], raw: string): void {
  if (!raw) return
  let last = 0
  const regex = new RegExp(URL_PATTERN)
  let match: RegExpExecArray | null
  while ((match = regex.exec(raw))) {
    const url = match[0]
    const href = url.replace(/[.,;:!?]+$/, '')
    if (match.index > last) {
      tokens.push({ kind: 'text', text: raw.slice(last, match.index) })
    }
    if (href.length > 0) tokens.push({ kind: 'link', text: href, href })
    const trailing = url.slice(href.length)
    if (trailing) tokens.push({ kind: 'text', text: trailing })
    last = match.index + url.length
  }
  if (last < raw.length) tokens.push({ kind: 'text', text: raw.slice(last) })
}

export function parseInline(source: string): InlineToken[] {
  const tokens: InlineToken[] = []
  const regex = new RegExp(INLINE_PATTERN)
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(source))) {
    if (match.index > lastIndex) {
      pushText(tokens, source.slice(lastIndex, match.index))
    }
    const [
      full,
      ,
      imageAlt,
      imageSrc,
      code,
      strongStar,
      strongUnderscore,
      emStar,
      emUnderscore,
      strike,
      link,
      href,
    ] = match
    if (imageAlt !== undefined && imageSrc !== undefined) {
      if (isSafeImageSrc(imageSrc)) {
        tokens.push({ kind: 'image', alt: imageAlt, src: imageSrc })
      } else {
        pushText(tokens, full)
      }
    } else if (code) {
      tokens.push({ kind: 'code', text: code.slice(1, -1) })
    } else if (strongStar) {
      tokens.push({ kind: 'strong', text: strongStar.slice(2, -2) })
    } else if (strongUnderscore) {
      tokens.push({ kind: 'strong', text: strongUnderscore.slice(2, -2) })
    } else if (emStar && isSafeWordBoundary(source, match.index)) {
      tokens.push({ kind: 'em', text: emStar.slice(1, -1) })
    } else if (emUnderscore && isSafeWordBoundary(source, match.index)) {
      tokens.push({ kind: 'em', text: emUnderscore.slice(1, -1) })
    } else if (strike) {
      tokens.push({ kind: 'strike', text: strike.slice(2, -2) })
    } else if (link) {
      const text = link.slice(1, link.indexOf(']'))
      if (isSafeHref(href)) {
        tokens.push({ kind: 'link', text, href })
      } else {
        pushText(tokens, full)
      }
    } else {
      pushText(tokens, full)
    }
    lastIndex = match.index + full.length
  }

  if (lastIndex < source.length) pushText(tokens, source.slice(lastIndex))
  return tokens
}
