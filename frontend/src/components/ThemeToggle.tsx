import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'

import { useI18n } from '../lib/i18n'
import { applyTheme, getStoredTheme, nextTheme, setTheme, type Theme } from '../lib/theme'

const LABELS: Record<Theme, string> = {
  system: 'layout.themeSystem',
  light: 'layout.themeLight',
  dark: 'layout.themeDark',
}

const FALLBACKS: Record<Theme, string> = {
  system: 'System theme',
  light: 'Light theme',
  dark: 'Dark theme',
}

export function ThemeToggle() {
  const { t } = useI18n()
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme())

  const cycle = () => {
    const next = nextTheme(theme)
    setTheme(next)
    applyTheme(next)
    setThemeState(next)
  }

  const Icon = theme === 'system' ? Monitor : theme === 'dark' ? Moon : Sun
  const label = t(LABELS[theme], FALLBACKS[theme])

  return (
    <button
      type="button"
      onClick={cycle}
      title={t('layout.switchTheme', '{theme} — click to switch', { theme: label })}
      aria-label={t('layout.switchThemeAria', '{theme}. Click to switch theme', { theme: label })}
      className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}
