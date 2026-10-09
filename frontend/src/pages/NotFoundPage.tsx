import { Link } from 'react-router-dom'

import { useI18n } from '../lib/i18n'

export function NotFoundPage() {
  const { t } = useI18n()
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-10 text-center">
      <p className="text-4xl font-bold text-slate-300">404</p>
      <h1 className="text-lg font-semibold text-slate-800">
        {t('misc.notFoundTitle', 'Page not found')}
      </h1>
      <p className="max-w-sm text-sm text-slate-500">
        {t(
          'misc.notFoundMessage',
          "The page you're looking for doesn't exist or you don't have access to it.",
        )}
      </p>
      <Link
        to="/organizations"
        className="mt-1 inline-flex items-center rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700"
      >
        {t('misc.backToWorkspaces', 'Back to workspaces')}
      </Link>
    </div>
  )
}
