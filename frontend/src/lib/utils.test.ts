import { describe, expect, it } from 'vitest'

import {
  avatarColor,
  cn,
  formatBytes,
  fromDateTimeLocal,
  initials,
  isOverdue,
  toDateTimeLocal,
} from './utils'

describe('cn', () => {
  it('joins truthy classes only', () => {
    expect(cn('a', false, undefined, null, 'b')).toBe('a b')
  })
})

describe('initials', () => {
  it('uses first and last name initials', () => {
    expect(initials('Ada Lovelace')).toBe('AL')
    expect(initials('Prince')).toBe('P')
    expect(initials('   ')).toBe('?')
  })
})

describe('avatarColor', () => {
  it('is deterministic per seed', () => {
    expect(avatarColor('ada@example.com')).toBe(avatarColor('ada@example.com'))
    expect(avatarColor('ada@example.com')).toMatch(/^bg-/)
  })
})

describe('formatBytes', () => {
  it('formats bytes with sensible units', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB')
  })
})

describe('isOverdue', () => {
  it('is false for done tasks and true for past due dates', () => {
    const past = new Date(Date.now() - 86_400_000).toISOString()
    expect(isOverdue(past, 'todo')).toBe(true)
    expect(isOverdue(past, 'done')).toBe(false)
    expect(isOverdue(null, 'todo')).toBe(false)
  })
})

describe('datetime-local helpers', () => {
  it('round-trips a local datetime string', () => {
    const local = '2026-07-14T09:30'
    const iso = fromDateTimeLocal(local)
    expect(iso).not.toBeNull()
    expect(toDateTimeLocal(iso)).toBe(local)
  })

  it('returns null/empty for invalid input', () => {
    expect(fromDateTimeLocal('')).toBeNull()
    expect(toDateTimeLocal(null)).toBe('')
  })
})
