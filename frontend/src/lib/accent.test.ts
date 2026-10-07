import { describe, expect, it } from 'vitest'

import { accentRamp, applyAccent, darkAccentRamp, isValidAccent } from './accent'

describe('isValidAccent', () => {
  it('accepts #RRGGBB and rejects other values', () => {
    expect(isValidAccent('#4f46e5')).toBe(true)
    expect(isValidAccent('#ABCDEF')).toBe(true)
    expect(isValidAccent('4f46e5')).toBe(false)
    expect(isValidAccent('#fff')).toBe(false)
    expect(isValidAccent(null)).toBe(false)
  })
})

describe('accentRamp', () => {
  it('derives the full brand ramp from the accent', () => {
    const ramp = accentRamp('#4f46e5')
    expect(Object.keys(ramp)).toHaveLength(10)
    expect(ramp['--color-brand-600']).toBe('#4f46e5')
    expect(ramp['--color-brand-50']).toContain('color-mix')
    expect(darkAccentRamp('#4f46e5')['--color-brand-600']).toContain('color-mix')
  })
})

describe('applyAccent', () => {
  it('injects a style tag and removes it for invalid colors', () => {
    applyAccent('#123456')
    expect(document.getElementById('teamflow-accent')).not.toBeNull()
    applyAccent(null)
    expect(document.getElementById('teamflow-accent')).toBeNull()
  })
})
