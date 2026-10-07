import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { preferencesApi } from '../lib/api'

export function UnsubscribePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [state, setState] = useState<'working' | 'done' | 'error'>(
    token ? 'working' : 'error',
  )

  useEffect(() => {
    if (!token) return
    preferencesApi
      .unsubscribe(token)
      .then(() => setState('done'))
      .catch(() => setState('error'))
  }, [token])

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
        <p className="text-sm font-bold tracking-tight text-brand-700">TeamFlow</p>
        {state === 'working' && (
          <p className="mt-3 text-sm text-slate-600">Updating your preferences…</p>
        )}
        {state === 'done' && (
          <>
            <p className="mt-3 text-sm font-medium text-slate-800">
              You will no longer receive email notifications.
            </p>
            <p className="mt-1 text-xs text-slate-500">
              You can turn them back on any time in Settings.
            </p>
          </>
        )}
        {state === 'error' && (
          <p className="mt-3 text-sm text-red-600">
            This unsubscribe link is invalid or has expired.
          </p>
        )}
        <Link
          to="/organizations"
          className="mt-4 inline-block text-xs font-medium text-brand-700 hover:underline"
        >
          Back to TeamFlow
        </Link>
      </div>
    </div>
  )
}
