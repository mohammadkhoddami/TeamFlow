import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useOrg } from '../OrgLayout'
import { useToast } from '../../contexts/toast'
import { ApiError, ssoApi } from '../../lib/api'
import { qk, useSsoConfig } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import { ROLE_LABELS, type MembershipRole } from '../../lib/types'
import { Badge, Button, Card, CardHeader, Checkbox, Field, Input, Select } from '../ui'

const DEFAULT_SCOPES = 'openid, email, profile'

export function SsoSection() {
  const { org } = useOrg()
  const toast = useToast()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const config = useSsoConfig(org.slug)

  const [issuer, setIssuer] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [scopes, setScopes] = useState(DEFAULT_SCOPES)
  const [isEnabled, setIsEnabled] = useState(true)
  const [autoProvision, setAutoProvision] = useState(true)
  const [defaultRole, setDefaultRole] = useState<MembershipRole>('member')

  useEffect(() => {
    if (!config.data) return
    setIssuer(config.data.issuer)
    setClientId(config.data.client_id)
    setScopes(config.data.scopes.join(', '))
    setIsEnabled(config.data.is_enabled)
    setAutoProvision(config.data.auto_provision)
    setDefaultRole(config.data.default_role)
  }, [config.data])

  const save = useMutation({
    mutationFn: () =>
      ssoApi.updateConfig(org.slug, {
        issuer: issuer.trim(),
        client_id: clientId.trim(),
        client_secret: clientSecret,
        scopes: scopes
          .split(',')
          .map((entry) => entry.trim())
          .filter(Boolean),
        is_enabled: isEnabled,
        auto_provision: autoProvision,
        default_role: defaultRole,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.ssoConfig(org.slug) })
      setClientSecret('')
      toast.success('SSO configuration saved')
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not save SSO configuration'),
  })

  return (
    <Card>
      <CardHeader
        title={t('settings.sso', 'Single sign-on (SSO)')}
        description="Connect an OIDC identity provider for your workspace."
        action={
          config.data && (
            <Badge
              className={
                config.data.has_secret
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-amber-100 text-amber-700'
              }
            >
              {config.data.has_secret ? 'Secret stored' : 'No secret'}
            </Badge>
          )
        }
      />
      <div className="space-y-4 p-5">
        {config.isError && (
          <p className="text-xs text-slate-500">
            SSO is not configured yet. Fill in the provider details to enable it.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Issuer URL" hint="The OIDC discovery issuer">
            <Input
              value={issuer}
              onChange={(event) => setIssuer(event.target.value)}
              placeholder="https://idp.example.com"
            />
          </Field>
          <Field label="Client ID">
            <Input value={clientId} onChange={(event) => setClientId(event.target.value)} />
          </Field>
        </div>
        <Field
          label="Client secret"
          hint={
            config.data?.has_secret
              ? 'A secret is stored; leave blank to keep it unchanged.'
              : 'Required the first time you save.'
          }
        >
          <Input
            type="password"
            value={clientSecret}
            onChange={(event) => setClientSecret(event.target.value)}
            placeholder="••••••••"
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Scopes" hint="Comma separated">
            <Input value={scopes} onChange={(event) => setScopes(event.target.value)} />
          </Field>
          <Field label="Default role" hint="Granted to auto-provisioned members">
            <Select
              value={defaultRole}
              onChange={(event) => setDefaultRole(event.target.value as MembershipRole)}
            >
              <option value="member">{ROLE_LABELS.member}</option>
              <option value="manager">{ROLE_LABELS.manager}</option>
              <option value="admin">{ROLE_LABELS.admin}</option>
            </Select>
          </Field>
        </div>
        <div className="flex flex-wrap gap-4">
          <Checkbox
            label="Enable SSO sign-in"
            checked={isEnabled}
            onChange={(event) => setIsEnabled(event.target.checked)}
          />
          <Checkbox
            label="Auto-provision new users"
            checked={autoProvision}
            onChange={(event) => setAutoProvision(event.target.checked)}
          />
        </div>
        <div className="flex justify-end">
          <Button
            onClick={() => save.mutate()}
            loading={save.isPending}
            disabled={!issuer.trim() || !clientId.trim()}
          >
            {t('common.save', 'Save')}
          </Button>
        </div>
      </div>
    </Card>
  )
}
