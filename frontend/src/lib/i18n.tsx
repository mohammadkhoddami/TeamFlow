import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { authApi } from './api'
import { tokens } from './tokens'

export type Locale = 'en' | 'fa'

export const LOCALE_STORAGE_KEY = 'teamflow.locale'

const DICTIONARIES: Record<Locale, Record<string, string>> = {
  en: {
    'nav.dashboard': 'Dashboard',
    'nav.projects': 'Projects',
    'nav.tasks': 'Tasks',
    'nav.reports': 'Reports',
    'nav.automations': 'Automations',
    'nav.integrations': 'Integrations',
    'nav.timesheet': 'Timesheet',
    'nav.members': 'Members',
    'nav.labels': 'Labels',
    'nav.webhooks': 'Webhooks',
    'nav.apiTokens': 'API access',
    'nav.audit': 'Audit log',
    'nav.settings': 'Settings',
    'nav.goals': 'Goals',
    'nav.dashboards': 'Dashboards',
    'nav.plugins': 'Plugins',
    'auth.signIn': 'Sign in',
    'auth.subtitle': 'Welcome back to TeamFlow',
    'auth.email': 'Email',
    'auth.password': 'Password',
    'auth.forgot': 'Forgot password?',
    'auth.otpLink': 'Email me a sign-in code',
    'auth.or': 'or',
    'auth.google': 'Continue with Google',
    'auth.noAccount': 'No account?',
    'auth.createOne': 'Create one',
    'auth.mfaTitle': 'Two-factor verification',
    'auth.mfaHint':
      'Enter the 6-digit code from your authenticator app, or one of your recovery codes.',
    'auth.mfaCode': 'Authentication code',
    'auth.verify': 'Verify',
    'auth.back': 'Back to sign in',
    'auth.sso': 'Sign in with SSO',
    'auth.ssoSlug': 'Workspace slug',
    'auth.ssoSlugPlaceholder': 'acme',
    'auth.ssoContinue': 'Continue with SSO',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.create': 'Create',
    'common.delete': 'Delete',
    'common.close': 'Close',
    'common.copy': 'Copy',
    'common.copied': 'Copied',
    'settings.title': 'Settings',
    'settings.subtitle': 'Your profile and the workspace.',
    'settings.profile': 'Your profile',
    'settings.sessions': 'Sessions',
    'settings.security': 'Security & sign-in',
    'settings.sso': 'Single sign-on (SSO)',
    'settings.scim': 'SCIM provisioning',
    'settings.roles': 'Custom roles',
    'settings.workspace': 'Workspace',
    'settings.language': 'Language & calendar',
    'settings.push': 'Push notifications',
    'settings.importExport': 'Import & export',
    'settings.emailNotifications': 'Email notifications',
  },
  fa: {
    'nav.dashboard': 'داشبورد',
    'nav.projects': 'پروژه‌ها',
    'nav.tasks': 'کارها',
    'nav.reports': 'گزارش‌ها',
    'nav.automations': 'اتوماسیون‌ها',
    'nav.integrations': 'یکپارچه‌سازی‌ها',
    'nav.timesheet': 'کارکرد',
    'nav.members': 'اعضا',
    'nav.labels': 'برچسب‌ها',
    'nav.webhooks': 'وب‌هوک‌ها',
    'nav.apiTokens': 'دسترسی API',
    'nav.audit': 'گزارش رویدادها',
    'nav.settings': 'تنظیمات',
    'nav.goals': 'اهداف',
    'nav.dashboards': 'داشبوردها',
    'nav.plugins': 'افزونه‌ها',
    'auth.signIn': 'ورود',
    'auth.subtitle': 'به TeamFlow خوش آمدید',
    'auth.email': 'ایمیل',
    'auth.password': 'گذرواژه',
    'auth.forgot': 'گذرواژه را فراموش کرده‌اید؟',
    'auth.otpLink': 'ارسال کد ورود به ایمیل',
    'auth.or': 'یا',
    'auth.google': 'ادامه با گوگل',
    'auth.noAccount': 'حساب ندارید؟',
    'auth.createOne': 'ساخت حساب',
    'auth.mfaTitle': 'تأیید دو مرحله‌ای',
    'auth.mfaHint':
      'کد ۶ رقمی برنامه احراز هویت یا یکی از کدهای بازیابی خود را وارد کنید.',
    'auth.mfaCode': 'کد احراز هویت',
    'auth.verify': 'تأیید',
    'auth.back': 'بازگشت به ورود',
    'auth.sso': 'ورود با SSO',
    'auth.ssoSlug': 'نامک فضای کاری',
    'auth.ssoSlugPlaceholder': 'acme',
    'auth.ssoContinue': 'ادامه با SSO',
    'common.save': 'ذخیره',
    'common.cancel': 'انصراف',
    'common.create': 'ایجاد',
    'common.delete': 'حذف',
    'common.close': 'بستن',
    'common.copy': 'کپی',
    'common.copied': 'کپی شد',
    'settings.title': 'تنظیمات',
    'settings.subtitle': 'پروفایل شما و فضای کاری.',
    'settings.profile': 'پروفایل شما',
    'settings.sessions': 'نشست‌ها',
    'settings.security': 'امنیت و ورود',
    'settings.sso': 'ورود یکپارچه (SSO)',
    'settings.scim': 'تأمین کاربران SCIM',
    'settings.roles': 'نقش‌های سفارشی',
    'settings.workspace': 'فضای کاری',
    'settings.language': 'زبان و تقویم',
    'settings.push': 'اعلان‌های پوش',
    'settings.importExport': 'ورود و خروج داده',
    'settings.emailNotifications': 'اعلان‌های ایمیلی',
  },
}

export function translate(locale: Locale, key: string, fallback?: string): string {
  return DICTIONARIES[locale]?.[key] ?? DICTIONARIES.en[key] ?? fallback ?? key
}

export function getStoredLocale(): Locale {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY) === 'fa' ? 'fa' : 'en'
  } catch {
    return 'en'
  }
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
  t: (key: string, fallback?: string) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getStoredLocale)

  useEffect(() => {
    applyDocumentLocale(locale)
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    storeLocale(next)
    if (tokens.hasSession()) {
      void authApi.updateMe({ locale: next }).catch(() => undefined)
    }
  }, [])

  const t = useCallback(
    (key: string, fallback?: string) => translate(locale, key, fallback),
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
