import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { ErrorState, PageSpinner } from '../components/ui'
import { useAuth } from '../contexts/auth'
import { ApiError } from '../lib/api'

export function OAuthCallbackPage() {
  const { completeOAuth } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  // The code is single-use; StrictMode double-invokes effects in dev, so the
  // exchange must only ever run once.
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    const code = params.get('code')
    if (!code || params.get('error')) {
      setError('Google sign-in was cancelled or could not be completed.')
      return
    }

    completeOAuth(code)
      .then((outcome) => {
        if (outcome.mfaRequired) {
          navigate('/login', { replace: true, state: { mfaToken: outcome.mfaToken } })
          return
        }
        navigate('/organizations', { replace: true })
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : 'Google sign-in failed')
      })
  }, [completeOAuth, navigate, params])

  if (!error) return <PageSpinner label="Completing sign-in…" />

  return (
    <AuthShell title="Sign-in failed" subtitle="We could not complete Google sign-in">
      <ErrorState message={error} />
      <p className="mt-4 text-center text-sm">
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  )
}
