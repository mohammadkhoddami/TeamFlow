export type Theme = 'system' | 'light' | 'dark'

const STORAGE_KEY = 'teamflow-theme'

export function getStoredTheme(): Theme {
  const value = window.localStorage.getItem(STORAGE_KEY)
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

function prefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function resolveDark(theme: Theme): boolean {
  return theme === 'dark' || (theme === 'system' && prefersDark())
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', resolveDark(theme))
  document.documentElement.style.colorScheme = resolveDark(theme) ? 'dark' : 'light'
}

export function setTheme(theme: Theme): void {
  window.localStorage.setItem(STORAGE_KEY, theme)
  applyTheme(theme)
}

export function nextTheme(theme: Theme): Theme {
  if (theme === 'system') return 'light'
  if (theme === 'light') return 'dark'
  return 'system'
}

/** Applies the stored theme and follows OS changes while in "system" mode. */
export function initTheme(): void {
  applyTheme(getStoredTheme())
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (getStoredTheme() === 'system') applyTheme('system')
  })
}
