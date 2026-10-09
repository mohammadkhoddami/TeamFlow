import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { useAuth } from '../contexts/auth'
import { authApi } from './api'
import { DICTIONARIES } from './locales'
import type { Locale } from './locales/types'
import { tokens } from './tokens'

export type { Locale } from './locales/types'

export const LOCALE_STORAGE_KEY = 'teamflow.locale'

export type TranslationVars = Record<string, string | number>

function interpolate(template: string, vars?: TranslationVars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  )
}

export function translate(
  locale: Locale,
  key: string,
  fallback?: string,
  vars?: TranslationVars,
): string {
  const raw = DICTIONARIES[locale]?.[key] ?? DICTIONARIES.en[key] ?? fallback ?? key
  return interpolate(raw, vars)
}

function storedLocaleValue(): string | null {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY)
  } catch {
    return null
  }
}

export function getStoredLocale(): Locale {
  return storedLocaleValue() === 'fa' ? 'fa' : 'en'
}

function storeLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    return
  }
}

function applyDocumentLocale(locale: Locale): void {
  document.documentElement.lang = locale
  document.documentElement.dir = locale === 'fa' ? 'rtl' : 'ltr'
}

interface I18nValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, fallback?: string, vars?: TranslationVars) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [locale, setLocaleState] = useState<Locale>(getStoredLocale)

  useEffect(() => {
    applyDocumentLocale(locale)
  }, [locale])

  // Adopt the account preference on a device that has no explicit local
  // choice yet, so the language follows the user across devices.
  useEffect(() => {
    if (!user?.locale) return
    if (storedLocaleValue() !== null) return
    if (user.locale !== 'en' && user.locale !== 'fa') return
    setLocaleState(user.locale)
    storeLocale(user.locale)
  }, [user])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    storeLocale(next)
    if (tokens.hasSession()) {
      void authApi.updateMe({ locale: next }).catch(() => undefined)
    }
  }, [])

  const t = useCallback(
    (key: string, fallback?: string, vars?: TranslationVars) =>
      translate(locale, key, fallback, vars),
    [locale],
  )

  const value = useMemo<I18nValue>(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used within LocaleProvider')
  return context
}
