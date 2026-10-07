import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, Field, Input, ErrorState } from '../components/ui'
import { useAuth } from '../contexts/auth'
import { ApiError, authApi, ssoApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

export function LoginPage() {
  const { login, verifyMfa } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [ssoOpen, setSsoOpen] = useState(false)
  const [ssoSlug, setSsoSlug] = useState('')

  function afterLogin() {
    const from = (location.state as { from?: string } | null)?.from
    navigate(from && from !== '/login' ? from : '/organizations', { replace: true })
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const outcome = await login(email, password)
      if (outcome.mfaRequired) {
        setMfaToken(outcome.mfaToken)
        return
      }
      afterLogin()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  async function submitMfa(event: React.FormEvent) {
    event.preventDefault()
    if (!mfaToken) return
    setBusy(true)
    setError(null)
    try {
      await verifyMfa(mfaToken, mfaCode.trim())
      afterLogin()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Verification failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title={mfaToken ? t('auth.mfaTitle', 'Two-factor verification') : t('auth.signIn', 'Sign in')}
      subtitle={mfaToken ? undefined : t('auth.subtitle', 'Welcome back to TeamFlow')}
      footer={
        mfaToken ? undefined : (
          <>
            {t('auth.noAccount', 'No account?')}{' '}
            <Link to="/register" className="font-medium text-brand-600 hover:text-brand-700">
              {t('auth.createOne', 'Create one')}
            </Link>
          </>
        )
      }
    >
      {mfaToken ? (
        <form className="space-y-4" onSubmit={submitMfa}>
          {error && <ErrorState message={error} />}
          <p className="text-sm text-slate-500">
            {t(
              'auth.mfaHint',
              'Enter the 6-digit code from your authenticator app, or one of your recovery codes.',
            )}
          </p>
          <Field label={t('auth.mfaCode', 'Authentication code')}>
            <Input
              autoFocus
              autoComplete="one-time-code"
              required
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value)}
              placeholder="123456"
            />
          </Field>
          <Button type="submit" className="w-full" loading={busy} disabled={!mfaCode.trim()}>
            {t('auth.verify', 'Verify')}
          </Button>
          <button
            type="button"
            className="w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700"
            onClick={() => {
              setMfaToken(null)
              setMfaCode('')
              setError(null)
            }}
          >
            {t('auth.back', 'Back to sign in')}
          </button>
        </form>
      ) : (
        <>
          <form className="space-y-4" onSubmit={submit}>
            {error && <ErrorState message={error} />}
            <Field label={t('auth.email', 'Email')}>
              <Input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
              />
            </Field>
            <Field label={t('auth.password', 'Password')}>
              <Input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••••"
              />
            </Field>
            <div className="flex items-center justify-between">
              <Link
                to="/login/otp"
                className="text-xs font-medium text-brand-600 hover:text-brand-700"
              >
                {t('auth.otpLink', 'Email me a sign-in code')}
              </Link>
              <Link
                to="/forgot-password"
                className="text-xs font-medium text-slate-500 hover:text-slate-700"
              >
                {t('auth.forgot', 'Forgot password?')}
              </Link>
            </div>
            <Button type="submit" className="w-full" loading={busy}>
              {t('auth.signIn', 'Sign in')}
            </Button>
          </form>

          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-slate-200" />
            <span className="text-xs font-medium text-slate-400">{t('auth.or', 'or')}</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>

          <a
            href={authApi.googleStartUrl()}
            className="flex w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M23.5 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.87c2.27-2.09 3.56-5.17 3.56-8.87Z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.24 0 5.95-1.08 7.94-2.91l-3.87-3c-1.08.72-2.45 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09A12 12 0 0 0 12 24Z"
              />
              <path
                fill="#FBBC05"
                d="M5.27 14.28a7.2 7.2 0 0 1 0-4.56V6.63H1.29a12 12 0 0 0 0 10.74l3.98-3.09Z"
              />
              <path
                fill="#EA4335"
                d="M12 4.75c1.76 0 3.35.61 4.6 1.8l3.43-3.43A11.98 11.98 0 0 0 12 0 12 12 0 0 0 1.29 6.63l3.98 3.09C6.22 6.87 8.87 4.75 12 4.75Z"
              />
            </svg>
            {t('auth.google', 'Continue with Google')}
          </a>

          <button
            type="button"
            className="mt-4 w-full text-center text-xs font-medium text-brand-600 hover:text-brand-700"
            onClick={() => setSsoOpen((value) => !value)}
          >
            {t('auth.sso', 'Sign in with SSO')}
          </button>

          {ssoOpen && (
            <div className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <Field label={t('auth.ssoSlug', 'Workspace slug')}>
                <Input
                  value={ssoSlug}
                  onChange={(event) => setSsoSlug(event.target.value)}
                  placeholder={t('auth.ssoSlugPlaceholder', 'acme')}
                />
              </Field>
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                disabled={!ssoSlug.trim()}
                onClick={() => {
                  window.location.href = ssoApi.startUrl(ssoSlug.trim())
                }}
              >
                {t('auth.ssoContinue', 'Continue with SSO')}
              </Button>
            </div>
          )}
        </>
      )}
    </AuthShell>
  )
}
