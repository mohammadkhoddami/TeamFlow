import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'

import { applyTheme, getStoredTheme, nextTheme, setTheme, type Theme } from '../lib/theme'

const LABELS: Record<Theme, string> = {
  system: 'System theme',
  light: 'Light theme',
  dark: 'Dark theme',
}

export function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme())

  const cycle = () => {
    const next = nextTheme(theme)
    setTheme(next)
    applyTheme(next)
    setThemeState(next)
  }

  const Icon = theme === 'system' ? Monitor : theme === 'dark' ? Moon : Sun

  return (
    <button
      type="button"
      onClick={cycle}
      title={`${LABELS[theme]} — click to switch`}
      aria-label={`${LABELS[theme]}. Click to switch theme`}
      className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}
