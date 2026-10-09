import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../OrgLayout'
import { useToast } from '../../contexts/toast'
import { API_BASE, ApiError, scimApi } from '../../lib/api'
import { qk, useScimTokens } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { ScimTokenCreated } from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  Field,
  Input,
  Modal,
} from '../ui'
import { formatDate, relativeTime } from '../../lib/utils'

export function ScimSection() {
  const { org } = useOrg()
  const toast = useToast()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const tokens = useScimTokens(org.slug)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [created, setCreated] = useState<ScimTokenCreated | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: qk.scimTokens(org.slug) })

  const create = useMutation({
    mutationFn: () => scimApi.createToken(org.slug, name.trim()),
    onSuccess: (token) => {
      invalidate()
      setCreating(false)
      setName('')
      setCreated(token)
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('settings.couldNotCreateScimToken', 'Could not create SCIM token'),
      ),
  })

  const revoke = useMutation({
    mutationFn: (tokenId: string) => scimApi.revokeToken(org.slug, tokenId),
    onSuccess: () => {
      invalidate()
      setRevoking(null)
      toast.success(t('settings.scimTokenRevoked', 'SCIM token revoked'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('settings.couldNotRevokeScimToken', 'Could not revoke SCIM token'),
      ),
  })

  return (
    <Card>
      <CardHeader
        title={t('settings.scim', 'SCIM provisioning')}
        description={t(
          'settings.scimDescription',
          'Let your identity provider push users and groups automatically.',
        )}
        action={
          <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" /> {t('settings.newToken', 'New token')}
          </Button>
        }
      />
      <div className="space-y-3 p-5">
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <p>
            {t('settings.baseUrl', 'Base URL:')}{' '}
            <code className="rounded bg-white px-1">{API_BASE}/scim/v2</code>
          </p>
          <p className="mt-0.5">
            {t('settings.authentication', 'Authentication:')}{' '}
            <code className="rounded bg-white px-1">Bearer &lt;token&gt;</code>
          </p>
        </div>
        {(tokens.data?.length ?? 0) === 0 && (
          <p className="text-sm text-slate-400">{t('settings.noScimTokens', 'No SCIM tokens.')}</p>
        )}
        {tokens.data?.map((token) => (
          <div
            key={token.id}
            className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800">
                {token.name}
                {!token.is_active && <Badge className="ml-2">{t('settings.revoked', 'revoked')}</Badge>}
              </p>
              <p className="text-xs text-slate-500">
                {token.last_used_at
                  ? t('settings.scimCreatedLastUsed', 'Created {date} · last used {time}', {
                      date: formatDate(token.created_at),
                      time: relativeTime(token.last_used_at),
                    })
                  : t('settings.scimCreatedOn', 'Created {date}', {
                      date: formatDate(token.created_at),
                    })}
              </p>
            </div>
            {token.is_active && (
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                title={t('settings.revoke', 'Revoke')}
                onClick={() => setRevoking(token.id)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t('settings.newScimToken', 'New SCIM token')}
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              disabled={!name.trim()}
            >
              {t('common.create', 'Create')}
            </Button>
          </>
        }
      >
        <Field label={t('common.name', 'Name')}>
          <Input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('settings.scimTokenNamePlaceholder', 'Okta provisioning')}
          />
        </Field>
      </Modal>

      <Modal
        open={Boolean(created)}
        onClose={() => setCreated(null)}
        title={t('settings.scimToken', 'SCIM token')}
        size="sm"
        footer={<Button onClick={() => setCreated(null)}>{t('common.close', 'Close')}</Button>}
      >
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            {t('settings.scimTokenCopyHint', 'Copy it now — it is never shown again.')}
          </p>
          <div className="flex items-center gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
            <span className="min-w-0 flex-1 break-all">{created?.token}</span>
            <button
              className="shrink-0 text-slate-400 hover:text-slate-700"
              onClick={() => {
                void navigator.clipboard.writeText(created?.token ?? '').then(
                  () => toast.success(t('common.copied', 'Copied')),
                  () => toast.error(t('settings.couldNotCopy', 'Could not copy')),
                )
              }}
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(revoking)}
        title={t('settings.revokeScimToken', 'Revoke SCIM token')}
        message={t(
          'settings.revokeScimTokenConfirm',
          'Requests using this token will fail immediately.',
        )}
        confirmLabel={t('settings.revoke', 'Revoke')}
        busy={revoke.isPending}
        onClose={() => setRevoking(null)}
        onConfirm={() => revoking && revoke.mutate(revoking)}
      />
    </Card>
  )
}
