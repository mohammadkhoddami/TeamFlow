import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound, Plus, RefreshCw, Trash2, UserCog } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, tokensApi } from '../lib/api'
import { useApiTokens, useOAuthApps, useServiceAccounts } from '../lib/hooks'
import type { ApiTokenCreated, ApiTokenRead, OAuthAppCreated, OAuthAppRead } from '../lib/types'
import { canManage } from '../lib/types'
import { formatDate, relativeTime } from '../lib/utils'

const SCOPES = ['read', 'write', 'admin'] as const

function SecretReveal({
  open,
  onClose,
  title,
  secret,
}: {
  open: boolean
  onClose: () => void
  title: string
  secret: string
}) {
  const toast = useToast()
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm" footer={<Button onClick={onClose}>Done</Button>}>
      <div className="space-y-2">
        <p className="text-xs text-slate-500">Copy it now — it is never shown again.</p>
        <div className="flex items-center gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
          <span className="min-w-0 flex-1 break-all">{secret}</span>
          <button
            className="shrink-0 text-slate-400 hover:text-slate-700"
            onClick={() => {
              void navigator.clipboard.writeText(secret).then(
                () => toast.success('Copied'),
                () => toast.error('Could not copy'),
              )
            }}
          >
            <Copy className="h-4 w-4" />
          </button>
        </div>
      </div>
    </Modal>
  )
}

export function ApiTokensPage() {
  const { org, role } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const elevated = canManage(role)
  const tokens = useApiTokens(org.slug)
  const serviceAccounts = useServiceAccounts(org.slug, elevated)
  const oauthApps = useOAuthApps(org.slug, elevated)

  const [tokenModal, setTokenModal] = useState(false)
  const [createdToken, setCreatedToken] = useState<ApiTokenCreated | null>(null)
  const [revoking, setRevoking] = useState<ApiTokenRead | null>(null)
  const [usageFor, setUsageFor] = useState<string | null>(null)
  const [accountModal, setAccountModal] = useState(false)
  const [appModal, setAppModal] = useState(false)
  const [createdSecret, setCreatedSecret] = useState<{ title: string; secret: string } | null>(null)

  const [tokenForm, setTokenForm] = useState({
    name: '',
    scopes: ['read', 'write'] as string[],
    expires_in_days: '',
    rate_limit_per_minute: '',
    service_account_id: '',
  })
  const [accountForm, setAccountForm] = useState({ name: '', description: '', scopes: ['read', 'write'] as string[] })
  const [appForm, setAppForm] = useState({ name: '', redirect_uris: '', scopes: ['read'] as string[] })

  const invalidateTokens = () => {
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'api-tokens'] })
  }
  const invalidateAccounts = () => {
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'service-accounts'] })
    invalidateTokens()
  }
  const invalidateApps = () =>
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'oauth-apps'] })

  const createToken = useMutation({
    mutationFn: () =>
      tokensApi.create(org.slug, {
        name: tokenForm.name.trim(),
        scopes: tokenForm.scopes,
        expires_in_days: tokenForm.expires_in_days ? Number(tokenForm.expires_in_days) : null,
        rate_limit_per_minute: tokenForm.rate_limit_per_minute
          ? Number(tokenForm.rate_limit_per_minute)
          : null,
        service_account_id: tokenForm.service_account_id || null,
      }),
    onSuccess: (created) => {
      setTokenModal(false)
      invalidateTokens()
      setCreatedToken(created)
      setTokenForm({ name: '', scopes: ['read', 'write'], expires_in_days: '', rate_limit_per_minute: '', service_account_id: '' })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not create token'),
  })

  const rotateToken = useMutation({
    mutationFn: (token: ApiTokenRead) => tokensApi.rotate(org.slug, token.id),
    onSuccess: (created) => {
      invalidateTokens()
      setCreatedToken(created)
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not rotate token'),
  })

  const revokeToken = useMutation({
    mutationFn: (token: ApiTokenRead) => tokensApi.revoke(org.slug, token.id),
    onSuccess: () => {
      invalidateTokens()
      setRevoking(null)
      toast.success('Token revoked')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not revoke token'),
  })

  const usage = useQuery({
    queryKey: ['orgs', org.slug, 'api-tokens', usageFor],
    queryFn: () => tokensApi.usage(org.slug, usageFor as string),
    enabled: Boolean(usageFor),
  })

  const createAccount = useMutation({
    mutationFn: () =>
      tokensApi.createServiceAccount(org.slug, {
        name: accountForm.name.trim(),
        description: accountForm.description.trim() || null,
        scopes: accountForm.scopes,
      }),
    onSuccess: () => {
      setAccountModal(false)
      invalidateAccounts()
      toast.success('Service account created')
      setAccountForm({ name: '', description: '', scopes: ['read', 'write'] })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not create account'),
  })

  const removeAccount = useMutation({
    mutationFn: (accountId: string) => tokensApi.removeServiceAccount(org.slug, accountId),
    onSuccess: () => {
      invalidateAccounts()
      toast.success('Service account deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete account'),
  })

  const createApp = useMutation({
    mutationFn: () =>
      tokensApi.createOAuthApp(org.slug, {
        name: appForm.name.trim(),
        redirect_uris: appForm.redirect_uris
          .split(/[\n,]/)
          .map((entry) => entry.trim())
          .filter(Boolean),
        scopes: appForm.scopes,
      }),
    onSuccess: (created) => {
      setAppModal(false)
      invalidateApps()
      setCreatedSecret({ title: 'OAuth client secret', secret: created.client_secret })
      setAppForm({ name: '', redirect_uris: '', scopes: ['read'] })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not create app'),
  })

  const rotateApp = useMutation({
    mutationFn: (app: OAuthAppRead) => tokensApi.rotateOAuthSecret(org.slug, app.id),
    onSuccess: (created: OAuthAppCreated) => {
      invalidateApps()
      setCreatedSecret({ title: 'New OAuth client secret', secret: created.client_secret })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not rotate secret'),
  })

  const removeApp = useMutation({
    mutationFn: (app: OAuthAppRead) => tokensApi.removeOAuthApp(org.slug, app.id),
    onSuccess: () => {
      invalidateApps()
      toast.success('OAuth app deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete app'),
  })

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">API access</h1>
        <p className="text-sm text-slate-500">
          Personal tokens, service accounts and OAuth apps — automations and CI never need a
          human password.
        </p>
      </div>

      {/* Personal access tokens */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
            <KeyRound className="h-4 w-4 text-slate-400" /> Personal access tokens
          </h2>
          <Button size="sm" onClick={() => setTokenModal(true)}>
            <Plus className="h-3.5 w-3.5" /> New token
          </Button>
        </div>
        {tokens.isLoading && <PageSpinner />}
        {tokens.isError && (
          <ErrorState message="Could not load tokens." onRetry={() => void tokens.refetch()} />
        )}
        {tokens.data?.length === 0 && (
          <EmptyState
            icon={<KeyRound className="h-8 w-8" />}
            title="No tokens yet"
            description="Create a token for the MCP server, CI or scripts."
          />
        )}
        <div className="space-y-2">
          {tokens.data?.map((token) => (
            <Card key={token.id} className="flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">
                  {token.name}
                  {!token.is_active && <Badge className="ml-2">revoked</Badge>}
                </p>
                <p className="text-xs text-slate-500">
                  <code className="rounded bg-slate-100 px-1">{token.token_prefix}…</code> ·{' '}
                  {token.scopes.join(', ')} · {token.usage_count} requests
                  {token.last_used_at ? ` · last ${relativeTime(token.last_used_at)}` : ''}
                  {token.expires_at ? ` · expires ${formatDate(token.expires_at)}` : ''}
                  {token.rate_limit_per_minute ? ` · ${token.rate_limit_per_minute}/min` : ''}
                </p>
                {usageFor === token.id && usage.data && (
                  <p className="mt-1 text-xs text-brand-700">
                    {usage.data.requests_last_minute} requests this minute · {usage.data.usage_count}{' '}
                    total
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setUsageFor(usageFor === token.id ? null : token.id)}
                >
                  Usage
                </Button>
                <Button size="sm" variant="ghost" title="Rotate" onClick={() => rotateToken.mutate(token)}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
                {token.is_active && (
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    onClick={() => setRevoking(token)}
                    title="Revoke"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Service accounts */}
      {elevated && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
              <UserCog className="h-4 w-4 text-slate-400" /> Service accounts
            </h2>
            <Button size="sm" variant="secondary" onClick={() => setAccountModal(true)}>
              <Plus className="h-3.5 w-3.5" /> New account
            </Button>
          </div>
          <p className="text-xs text-slate-500">
            Non-human identities with scoped tokens; hidden from the member roster.
          </p>
          {(serviceAccounts.data?.length ?? 0) === 0 && (
            <p className="text-sm text-slate-400">No service accounts.</p>
          )}
          {serviceAccounts.data?.map((account) => (
            <Card key={account.id} className="flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">
                  {account.name}
                  {!account.is_active && <Badge className="ml-2">disabled</Badge>}
                </p>
                <p className="text-xs text-slate-500">
                  {account.scopes.join(', ')}
                  {account.description ? ` · ${account.description}` : ''}
                </p>
              </div>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                onClick={() => removeAccount.mutate(account.id)}
                title="Delete service account"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </Card>
          ))}
        </section>
      )}

      {/* OAuth apps */}
      {elevated && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-800">OAuth apps</h2>
            <Button size="sm" variant="secondary" onClick={() => setAppModal(true)}>
              <Plus className="h-3.5 w-3.5" /> New OAuth app
            </Button>
          </div>
          <p className="text-xs text-slate-500">
            Client-credentials access for server-to-server integrations
            (<code className="rounded bg-slate-100 px-1">POST /api/v1/oauth/token</code>).
          </p>
          {(oauthApps.data?.length ?? 0) === 0 && (
            <p className="text-sm text-slate-400">No OAuth apps registered.</p>
          )}
          {oauthApps.data?.map((app) => (
            <Card key={app.id} className="flex flex-wrap items-center gap-3 p-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">{app.name}</p>
                <p className="text-xs text-slate-500">
                  client_id <code className="rounded bg-slate-100 px-1">{app.client_id}</code> ·{' '}
                  {app.scopes.join(', ')}
                  {app.last_used_at ? ` · last ${relativeTime(app.last_used_at)}` : ''}
                </p>
              </div>
              <Button size="sm" variant="ghost" title="Rotate secret" onClick={() => rotateApp.mutate(app)}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                onClick={() => removeApp.mutate(app)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </Card>
          ))}
        </section>
      )}

      {/* Create token modal */}
      <Modal
        open={tokenModal}
        onClose={() => setTokenModal(false)}
        title="New API token"
        footer={
          <>
            <Button variant="secondary" onClick={() => setTokenModal(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createToken.mutate()}
              disabled={!tokenForm.name.trim() || tokenForm.scopes.length === 0}
              loading={createToken.isPending}
            >
              Create token
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name">
            <Input
              value={tokenForm.name}
              maxLength={128}
              onChange={(event) => setTokenForm({ ...tokenForm, name: event.target.value })}
              placeholder="CI deploy token"
            />
          </Field>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">Scopes</p>
            {SCOPES.map((scope) => (
              <Checkbox
                key={scope}
                label={scope}
                checked={tokenForm.scopes.includes(scope)}
                onChange={(event) =>
                  setTokenForm({
                    ...tokenForm,
                    scopes: event.target.checked
                      ? [...tokenForm.scopes, scope]
                      : tokenForm.scopes.filter((entry) => entry !== scope),
                  })
                }
              />
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Expires in (days)" hint="Empty = no expiry">
              <Input
                type="number"
                min={1}
                value={tokenForm.expires_in_days}
                onChange={(event) =>
                  setTokenForm({ ...tokenForm, expires_in_days: event.target.value })
                }
              />
            </Field>
            <Field label="Rate limit / minute" hint="Empty = unlimited">
              <Input
                type="number"
                min={1}
                value={tokenForm.rate_limit_per_minute}
                onChange={(event) =>
                  setTokenForm({ ...tokenForm, rate_limit_per_minute: event.target.value })
                }
              />
            </Field>
          </div>
          {elevated && (serviceAccounts.data?.length ?? 0) > 0 && (
            <Field label="Owner" hint="Attach to a service account instead of yourself">
              <Select
                value={tokenForm.service_account_id}
                onChange={(event) =>
                  setTokenForm({ ...tokenForm, service_account_id: event.target.value })
                }
              >
                <option value="">Me</option>
                {serviceAccounts.data?.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
      </Modal>

      {/* Create service account modal */}
      <Modal
        open={accountModal}
        onClose={() => setAccountModal(false)}
        title="New service account"
        footer={
          <>
            <Button variant="secondary" onClick={() => setAccountModal(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createAccount.mutate()}
              disabled={!accountForm.name.trim()}
              loading={createAccount.isPending}
            >
              Create account
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name">
            <Input
              value={accountForm.name}
              maxLength={128}
              onChange={(event) => setAccountForm({ ...accountForm, name: event.target.value })}
              placeholder="Deploy bot"
            />
          </Field>
          <Field label="Description">
            <Input
              value={accountForm.description}
              maxLength={2000}
              onChange={(event) =>
                setAccountForm({ ...accountForm, description: event.target.value })
              }
            />
          </Field>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">Max scopes</p>
            {SCOPES.map((scope) => (
              <Checkbox
                key={scope}
                label={scope}
                checked={accountForm.scopes.includes(scope)}
                onChange={(event) =>
                  setAccountForm({
                    ...accountForm,
                    scopes: event.target.checked
                      ? [...accountForm.scopes, scope]
                      : accountForm.scopes.filter((entry) => entry !== scope),
                  })
                }
              />
            ))}
          </div>
        </div>
      </Modal>

      {/* Create OAuth app modal */}
      <Modal
        open={appModal}
        onClose={() => setAppModal(false)}
        title="Register OAuth app"
        footer={
          <>
            <Button variant="secondary" onClick={() => setAppModal(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createApp.mutate()}
              disabled={!appForm.name.trim()}
              loading={createApp.isPending}
            >
              Register app
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name">
            <Input
              value={appForm.name}
              maxLength={128}
              onChange={(event) => setAppForm({ ...appForm, name: event.target.value })}
            />
          </Field>
          <Field label="Redirect URIs" hint="One per line (optional for client credentials)">
            <Input
              value={appForm.redirect_uris}
              onChange={(event) => setAppForm({ ...appForm, redirect_uris: event.target.value })}
              placeholder="https://example.com/oauth/callback"
            />
          </Field>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">Registered scopes</p>
            {SCOPES.map((scope) => (
              <Checkbox
                key={scope}
                label={scope}
                checked={appForm.scopes.includes(scope)}
                onChange={(event) =>
                  setAppForm({
                    ...appForm,
                    scopes: event.target.checked
                      ? [...appForm.scopes, scope]
                      : appForm.scopes.filter((entry) => entry !== scope),
                  })
                }
              />
            ))}
          </div>
        </div>
      </Modal>

      <SecretReveal
        open={Boolean(createdToken)}
        onClose={() => setCreatedToken(null)}
        title="API token"
        secret={createdToken?.token ?? ''}
      />
      <SecretReveal
        open={Boolean(createdSecret)}
        onClose={() => setCreatedSecret(null)}
        title={createdSecret?.title ?? 'Client secret'}
        secret={createdSecret?.secret ?? ''}
      />

      <ConfirmDialog
        open={Boolean(revoking)}
        title="Revoke API token"
        message={`Revoke "${revoking?.name ?? ''}"? Requests with it will fail immediately.`}
        busy={revokeToken.isPending}
        onClose={() => setRevoking(null)}
        onConfirm={() => revoking && revokeToken.mutate(revoking)}
      />
    </div>
  )
}
