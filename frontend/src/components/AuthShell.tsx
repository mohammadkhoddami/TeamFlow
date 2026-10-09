import type { ReactNode } from 'react'

import { useI18n } from '../lib/i18n'
import { LanguageToggle } from './LanguageToggle'

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
}) {
  const { t } = useI18n()
  return (
    <div className="relative flex min-h-full items-center justify-center bg-slate-50 px-4 py-10">
      <div className="absolute end-4 top-4">
        <LanguageToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-lg font-bold tracking-tight text-brand-700">
            {t('common.brand', 'TeamFlow')}
          </p>
          <h1 className="mt-3 text-xl font-semibold text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">{children}</div>
        {footer && <div className="mt-4 text-center text-sm text-slate-500">{footer}</div>}
      </div>
    </div>
  )
}
