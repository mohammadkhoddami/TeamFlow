import { describe, expect, it } from 'vitest'

import { translate } from './i18n'

describe('translate', () => {
  it('returns the locale string when present', () => {
    expect(translate('en', 'nav.dashboard')).toBe('Dashboard')
    expect(translate('fa', 'nav.dashboard')).toBe('داشبورد')
  })

  it('falls back to English, then the caller fallback, then the key', () => {
    expect(translate('fa', 'auth.sso')).toBe('ورود با SSO')
    expect(translate('fa', 'missing.key', 'Fallback')).toBe('Fallback')
    expect(translate('en', 'missing.key')).toBe('missing.key')
  })
})
