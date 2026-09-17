import { useState } from 'react'
import { Link } from 'react-router-dom'

import { AuthShell } from '../components/AuthShell'
import { Button, ErrorState, Field, Input } from '../components/ui'
import { ApiError, authApi } from '../lib/api'

export function ForgotPasswordPage() {
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
      setError(err instanceof ApiError ? err.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="Reset your password"
      subtitle="We'll email you a single-use reset link"
      footer={
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          Back to sign in
        </Link>
      }
    >
      {sent ? (
        <p className="text-sm text-slate-600">
          If an account exists for <span className="font-medium">{email}</span>, a reset link is on
          its way. Check your inbox (and the backend console in development).
        </p>
      ) : (
        <form className="space-y-4" onSubmit={submit}>
          {error && <ErrorState message={error} />}
          <Field label="Email">
            <Input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
            />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>
            Send reset link
          </Button>
        </form>
      )}
    </AuthShell>
  )
}
