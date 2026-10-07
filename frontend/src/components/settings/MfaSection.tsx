import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, ShieldCheck, ShieldOff } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, mfaApi } from '../../lib/api'
import { qk, useMfaStatus } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { MfaSetup } from '../../lib/types'
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Modal } from '../ui'

function CopyButton({ value }: { value: string }) {
  const toast = useToast()
  const { t } = useI18n()
  return (
    <button
      className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      title={t('common.copy', 'Copy')}
      onClick={() => {
        void navigator.clipboard.writeText(value).then(
          () => toast.success(t('common.copied', 'Copied')),
          () => toast.error('Could not copy'),
        )
      }}
    >
      <Copy className="h-3.5 w-3.5" />
    </button>
  )
}

export function MfaSection() {
  const toast = useToast()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const status = useMfaStatus()
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [code, setCode] = useState('')
  const [disableOpen, setDisableOpen] = useState(false)
  const [disableCode, setDisableCode] = useState('')
  const [error, setError] = useState<string | null>(null)

  const startSetup = useMutation({
    mutationFn: () => mfaApi.setup(),
    onSuccess: (data) => {
      setSetup(data)
      setCode('')
      setError(null)
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not start MFA setup'),
  })

  const enable = useMutation({
    mutationFn: () => mfaApi.enable(code.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.mfaStatus })
      setSetup(null)
      toast.success('Two-factor authentication enabled')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not verify code'),
  })

  const disable = useMutation({
    mutationFn: () => mfaApi.disable(disableCode.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.mfaStatus })
      setDisableOpen(false)
      setDisableCode('')
      toast.success('Two-factor authentication disabled')
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not disable MFA'),
  })

  return (
    <Card>
      <CardHeader
        title={t('settings.security', 'Security & sign-in')}
        description="Protect your account with a TOTP authenticator app."
        action={
          status.data && (
            <Badge
              className={
                status.data.enabled
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-slate-100 text-slate-600'
              }
            >
              {status.data.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
          )
        }
      />
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-md text-sm text-slate-600">
            {status.data?.enabled
              ? 'Sign-in requires a code from your authenticator app.'
              : 'Add a second factor so a stolen password is not enough to sign in.'}
          </p>
          <div className="flex items-center gap-2">
            {status.data?.enabled ? (
              <>
                <ShieldCheck className="h-4 w-4 text-emerald-500" />
                <Button variant="danger" size="sm" onClick={() => setDisableOpen(true)}>
                  <ShieldOff className="h-3.5 w-3.5" /> Disable
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={() => startSetup.mutate()}
                loading={startSetup.isPending}
              >
                <ShieldCheck className="h-3.5 w-3.5" /> Set up MFA
              </Button>
            )}
          </div>
        </div>
      </div>

      <Modal
        open={Boolean(setup)}
        onClose={() => setSetup(null)}
        title="Set up two-factor authentication"
        description="Add the secret to your authenticator app, then confirm with a code."
        footer={
          <>
            <Button variant="secondary" onClick={() => setSetup(null)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => enable.mutate()}
              loading={enable.isPending}
              disabled={!code.trim()}
            >
              {t('auth.verify', 'Verify')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <div>
            <p className="text-sm font-medium text-slate-700">otpauth URI</p>
            <div className="mt-1 flex items-start gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
              <span className="min-w-0 flex-1 break-all">{setup?.otpauth_uri}</span>
              <CopyButton value={setup?.otpauth_uri ?? ''} />
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-700">Secret</p>
            <div className="mt-1 flex items-center gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
              <span className="min-w-0 flex-1 break-all">{setup?.secret}</span>
              <CopyButton value={setup?.secret ?? ''} />
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-slate-700">Recovery codes</p>
            <div className="mt-1 grid grid-cols-2 gap-1 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
              {(setup?.recovery_codes ?? []).map((recovery) => (
                <span key={recovery}>{recovery}</span>
              ))}
              <button
                className="col-span-2 mt-1 justify-self-start text-slate-400 hover:text-slate-700"
                onClick={() => {
                  void navigator.clipboard
                    .writeText((setup?.recovery_codes ?? []).join('\n'))
                    .then(
                      () => toast.success(t('common.copied', 'Copied')),
                      () => toast.error('Could not copy'),
                    )
                }}
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <Field label={t('auth.mfaCode', 'Authentication code')}>
            <Input
              autoFocus
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="123456"
            />
          </Field>
        </div>
      </Modal>

      <Modal
        open={disableOpen}
        onClose={() => setDisableOpen(false)}
        title="Disable two-factor authentication"
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDisableOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              variant="danger"
              onClick={() => disable.mutate()}
              loading={disable.isPending}
              disabled={!disableCode.trim()}
            >
              Disable
            </Button>
          </>
        }
      >
        <Field
          label="Code"
          hint="A TOTP code or one of your recovery codes is required."
        >
          <Input
            autoFocus
            value={disableCode}
            onChange={(event) => setDisableCode(event.target.value)}
          />
        </Field>
      </Modal>
    </Card>
  )
}
