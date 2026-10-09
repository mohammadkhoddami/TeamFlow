import { useI18n } from '../lib/i18n'

export function LanguageToggle() {
  const { locale, setLocale, t } = useI18n()
  const next = locale === 'fa' ? 'en' : 'fa'

  return (
    <button
      type="button"
      onClick={() => setLocale(next)}
      title={t('layout.switchLanguage', 'Switch language')}
      aria-label={t('layout.switchLanguageAria', 'Switch language to {language}', {
        language: next === 'fa' ? 'فارسی' : 'English',
      })}
      className="rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
    >
      {locale === 'fa' ? 'EN' : 'فا'}
    </button>
  )
}
