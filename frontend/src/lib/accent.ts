const STYLE_ID = 'teamflow-accent'
const HEX_RE = /^#[0-9a-fA-F]{6}$/

export function isValidAccent(value: string | null | undefined): value is string {
  return typeof value === 'string' && HEX_RE.test(value)
}

function mix(color: string, percentage: number, other: string): string {
  return `color-mix(in srgb, ${color} ${percentage}%, ${other})`
}

export function accentRamp(color: string): Record<string, string> {
  return {
    '--color-brand-50': mix(color, 10, 'white'),
    '--color-brand-100': mix(color, 20, 'white'),
    '--color-brand-200': mix(color, 35, 'white'),
    '--color-brand-300': mix(color, 55, 'white'),
    '--color-brand-400': mix(color, 75, 'white'),
    '--color-brand-500': mix(color, 90, 'white'),
    '--color-brand-600': color,
    '--color-brand-700': mix(color, 85, 'black'),
    '--color-brand-800': mix(color, 70, 'black'),
    '--color-brand-900': mix(color, 55, 'black'),
  }
}

export function darkAccentRamp(color: string): Record<string, string> {
  return {
    '--color-brand-50': mix(color, 25, 'black'),
    '--color-brand-100': mix(color, 35, 'black'),
    '--color-brand-200': mix(color, 50, 'black'),
    '--color-brand-300': mix(color, 65, 'black'),
    '--color-brand-400': mix(color, 80, 'black'),
    '--color-brand-500': mix(color, 95, 'black'),
    '--color-brand-600': mix(color, 85, 'white'),
    '--color-brand-700': mix(color, 70, 'white'),
    '--color-brand-800': mix(color, 55, 'white'),
    '--color-brand-900': mix(color, 40, 'white'),
  }
}

function rule(selector: string, variables: Record<string, string>): string {
  const body = Object.entries(variables)
    .map(([name, value]) => `${name}: ${value};`)
    .join(' ')
  return `${selector} { ${body} }`
}

/**
 * Overrides Tailwind's `--color-brand-*` ramp with a per-workspace accent.
 * A dedicated <style> tag keeps the `.dark` selector working (an inline
 * style on <html> would beat it regardless of theme).
 */
export function applyAccent(color: string | null | undefined): void {
  const existing = document.getElementById(STYLE_ID)
  if (!isValidAccent(color)) {
    existing?.remove()
    return
  }
  const style = existing ?? document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `${rule(':root', accentRamp(color))}\n${rule('.dark', darkAccentRamp(color))}`
  if (!existing) document.head.appendChild(style)
}
