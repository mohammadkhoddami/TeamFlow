import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, ErrorState, Field, Input } from '../components/ui'
import { ApiError, authApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

export function ResetPasswordPage() {
  const { t } = useI18n()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (password.length < 10) {
      setError(t('auth.passwordMinLength', 'Password must be at least 10 characters'))
      return
    }
    if (password !== confirm) {
      setError(t('auth.passwordsMismatch', 'Passwords do not match'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await authApi.resetPassword(token, password)
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.resetFailed', 'Reset failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title={t('auth.newPasswordTitle', 'Choose a new password')}
      footer={
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          {t('auth.back', 'Back to sign in')}
        </Link>
      }
    >
      {!token ? (
        <ErrorState
          message={t(
            'auth.missingResetToken',
            'This reset link is missing its token. Request a new one.',
          )}
        />
      ) : (
        <form className="space-y-4" onSubmit={submit}>
          {error && <ErrorState message={error} />}
          <Field
            label={t('auth.newPassword', 'New password')}
            hint={t('auth.passwordHint', 'At least 10 characters')}
          >
            <Input
              type="password"
              required
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          <Field label={t('auth.confirmNewPassword', 'Confirm new password')}>
            <Input
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>
            {t('auth.resetPassword', 'Reset password')}
          </Button>
        </form>
      )}
    </AuthShell>
  )
}
