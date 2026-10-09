import { useState } from 'react'
import { Link } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, ErrorState, Field, Input } from '../components/ui'
import { ApiError, authApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

export function ForgotPasswordPage() {
  const { t } = useI18n()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await authApi.forgotPassword(email)
      setSent(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.requestFailed', 'Request failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title={t('auth.forgotTitle', 'Reset your password')}
      subtitle={t('auth.forgotSubtitle', "We'll email you a single-use reset link")}
      footer={
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          {t('auth.back', 'Back to sign in')}
        </Link>
      }
    >
      {sent ? (
        <p className="text-sm text-slate-600">
          {t(
            'auth.resetSent',
            'If an account exists for {email}, a reset link is on its way. Check your inbox (and the backend console in development).',
            { email },
          )}
        </p>
      ) : (
        <form className="space-y-4" onSubmit={submit}>
          {error && <ErrorState message={error} />}
          <Field label={t('auth.email', 'Email')}>
            <Input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
            />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>
            {t('auth.sendResetLink', 'Send reset link')}
          </Button>
        </form>
      )}
    </AuthShell>
  )
}
