import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, ErrorState, Field, Input } from '../components/ui'
import { useAuth } from '../contexts/auth'
import { ApiError, authApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

export function OtpPage() {
  const { loginWithOtp } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [stage, setStage] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function requestCode() {
    setBusy(true)
    setError(null)
    try {
      await authApi.requestOtp(email)
      setStage('code')
      setCode('')
      setNotice(
        t(
          'auth.signInCodeSentTo',
          'We emailed a sign-in code to {email}. It expires in 10 minutes.',
          { email },
        ),
      )
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t('auth.sendSignInCodeFailed', 'Could not send the code'),
      )
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (stage === 'email') {
      await requestCode()
      return
    }
    setBusy(true)
    setError(null)
    try {
      const outcome = await loginWithOtp(email, code)
      if (outcome.mfaRequired) {
        navigate('/login', { replace: true, state: { mfaToken: outcome.mfaToken } })
        return
      }
      navigate('/organizations', { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t('auth.signInFailed', 'Sign-in failed'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title={t('auth.otpTitle', 'Sign in with email')}
      subtitle={t('auth.otpSubtitle', 'We will email you a one-time code — no password needed')}
      footer={
        <>
          {t('auth.preferPassword', 'Prefer a password?')}{' '}
          <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
            {t('auth.signIn', 'Sign in')}
          </Link>
        </>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        {error && <ErrorState message={error} />}
        {notice && (
          <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">{notice}</p>
        )}
        <Field label={t('auth.email', 'Email')}>
          <Input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            disabled={stage === 'code'}
          />
        </Field>
        {stage === 'code' && (
          <Field
            label={t('auth.signInCode', 'Sign-in code')}
            hint={t('auth.codeFromEmail', 'The 6-digit code from the email')}
          >
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={6}
              required
              autoFocus
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
              placeholder="123456"
            />
          </Field>
        )}
        <Button type="submit" className="w-full" loading={busy}>
          {stage === 'email' ? t('auth.emailMeCode', 'Email me a code') : t('auth.signIn', 'Sign in')}
        </Button>
        {stage === 'code' && (
          <button
            type="button"
            className="w-full text-center text-xs font-medium text-slate-500 hover:text-slate-700 disabled:opacity-50"
            disabled={busy}
            onClick={requestCode}
          >
            {t('auth.sendNewCode', 'Send a new code')}
          </button>
        )}
      </form>
    </AuthShell>
  )
}
