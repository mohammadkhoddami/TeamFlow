import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, ErrorState, Field, Input } from '../components/ui'
import { useAuth } from '../contexts/auth'
import { ApiError, authApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

export function RegisterPage() {
  const { register } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [stage, setStage] = useState<'details' | 'code'>('details')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function sendCode() {
    setBusy(true)
    setError(null)
    try {
      await authApi.requestOtp(email)
      setStage('code')
      setCode('')
      setNotice(
        t(
          'auth.verificationSentTo',
          'We emailed a verification code to {email}. It expires in 10 minutes.',
          { email },
        ),
      )
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t('auth.sendCodeFailed', 'Could not send the verification code'),
      )
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (stage === 'details') {
      if (password.length < 10) {
        setError(t('auth.passwordMinLength', 'Password must be at least 10 characters'))
        return
      }
      if (password !== confirm) {
        setError(t('auth.passwordsMismatch', 'Passwords do not match'))
        return
      }
      await sendCode()
      return
    }
    setBusy(true)
    setError(null)
    try {
      await register({ email, password, full_name: fullName, code })
      navigate('/organizations', { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : t('auth.registrationFailed', 'Registration failed'),
      )
    } finally {
      setBusy(false)
    }
  }

  function backToDetails() {
    setStage('details')
    setCode('')
    setError(null)
    setNotice(null)
  }

  return (
    <AuthShell
      title={t('auth.registerTitle', 'Create your account')}
      subtitle={
        stage === 'details'
          ? t('auth.registerSubtitle', 'Start collaborating with your team')
          : t('auth.registerCodeSubtitle', 'Enter the code we emailed you to finish')
      }
      footer={
        <>
          {t('auth.alreadyRegistered', 'Already registered?')}{' '}
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
        <Field label={t('auth.fullName', 'Full name')}>
          <Input
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="Ada Lovelace"
            maxLength={255}
            disabled={stage === 'code'}
          />
        </Field>
        <Field label={t('auth.email', 'Email')}>
          <Input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            disabled={stage === 'code'}
          />
        </Field>
        {stage === 'details' ? (
          <>
            <Field
              label={t('auth.password', 'Password')}
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
            <Field label={t('auth.confirmPassword', 'Confirm password')}>
              <Input
                type="password"
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </Field>
          </>
        ) : (
          <Field
            label={t('auth.verificationCode', 'Verification code')}
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
          {stage === 'details'
            ? t('auth.sendVerificationCode', 'Send verification code')
            : t('auth.createAccount', 'Create account')}
        </Button>
        {stage === 'code' && (
          <div className="flex items-center justify-between text-xs font-medium text-slate-500">
            <button
              type="button"
              className="hover:text-slate-700 disabled:opacity-50"
              disabled={busy}
              onClick={backToDetails}
            >
              {t('auth.useDifferentEmail', 'Use a different email')}
            </button>
            <button
              type="button"
              className="hover:text-slate-700 disabled:opacity-50"
              disabled={busy}
              onClick={sendCode}
            >
              {t('auth.sendNewCode', 'Send a new code')}
            </button>
          </div>
        )}
      </form>
    </AuthShell>
  )
}
