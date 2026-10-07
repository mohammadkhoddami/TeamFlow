import { describe, expect, it } from 'vitest'

import {
  isSafeHref,
  isSafeImageSrc,
  parseInline,
  parseMarkdown,
} from './markdown'

describe('parseMarkdown', () => {
  it('parses headings, lists, code and quotes', () => {
    const blocks = parseMarkdown(
      '# Title\n\n- one\n- two\n\n```python\nprint(1)\n```\n\n> quoted',
    )
    expect(blocks[0]).toEqual({ kind: 'heading', level: 1, text: 'Title' })
    expect(blocks[1]).toEqual({ kind: 'list', ordered: false, items: ['one', 'two'] })
    expect(blocks[2]).toMatchObject({ kind: 'code', language: 'python' })
    expect(blocks[3]).toEqual({ kind: 'quote', text: 'quoted' })
  })

  it('parses GFM tables with alignment', () => {
    const blocks = parseMarkdown(
      '| Name | Count |\n| :--- | ---: |\n| Ada | 2 |\n| Alan | 3 |',
    )
    expect(blocks).toHaveLength(1)
    const table = blocks[0]
    expect(table.kind).toBe('table')
    if (table.kind !== 'table') return
    expect(table.header).toEqual(['Name', 'Count'])
    expect(table.align).toEqual(['left', 'right'])
    expect(table.rows).toEqual([
      ['Ada', '2'],
      ['Alan', '3'],
    ])
  })

  it('parses standalone images as image blocks', () => {
    const blocks = parseMarkdown('![diagram](attachment://abc-123)')
    expect(blocks).toEqual([{ kind: 'image', alt: 'diagram', src: 'attachment://abc-123' }])
  })

  it('does not treat a table-looking line without a divider as a table', () => {
    const blocks = parseMarkdown('| just | a | sentence |')
    expect(blocks[0].kind).toBe('paragraph')
  })
})

describe('parseInline', () => {
  it('parses inline images before links', () => {
    const tokens = parseInline('see ![shot](attachment://42) now')
    expect(tokens).toEqual([
      { kind: 'text', text: 'see ' },
      { kind: 'image', alt: 'shot', src: 'attachment://42' },
      { kind: 'text', text: ' now' },
    ])
  })

  it('keeps unsafe image sources as text', () => {
    const tokens = parseInline('![x](javascript:alert(1))')
    // javascript: URLs have parentheses so the markdown link pattern fails and
    // the raw text survives — either way it must never become an image token.
    expect(tokens.some((token) => token.kind === 'image')).toBe(false)
  })

  it('parses emphasis, code and links', () => {
    const tokens = parseInline('**bold** `code` [x](https://e.com)')
    expect(tokens).toEqual([
      { kind: 'strong', text: 'bold' },
      { kind: 'text', text: ' ' },
      { kind: 'code', text: 'code' },
      { kind: 'text', text: ' ' },
      { kind: 'link', text: 'x', href: 'https://e.com' },
    ])
  })
})

describe('safety helpers', () => {
  it('accepts http(s), mailto and relative links', () => {
    expect(isSafeHref('https://example.com')).toBe(true)
    expect(isSafeHref('mailto:a@b.c')).toBe(true)
    expect(isSafeHref('/tasks/1')).toBe(true)
    expect(isSafeHref('javascript:alert(1)')).toBe(false)
  })

  it('accepts http(s), relative and attachment image sources only', () => {
    expect(isSafeImageSrc('attachment://uuid')).toBe(true)
    expect(isSafeImageSrc('https://cdn.example.com/a.png')).toBe(true)
    expect(isSafeImageSrc('/static/a.png')).toBe(true)
    expect(isSafeImageSrc('data:image/png;base64,AAAA')).toBe(false)
    expect(isSafeImageSrc('javascript:alert(1)')).toBe(false)
  })
})
