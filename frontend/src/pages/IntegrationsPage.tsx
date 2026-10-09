import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Plug, Plus, RefreshCw, Trash2 } from 'lucide-react'
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
import { API_BASE, ApiError, integrationsApi } from '../lib/api'
import { useIntegrationEvents, useIntegrations } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import type { IntegrationCreated, IntegrationProvider, IntegrationRead } from '../lib/types'
import {
  INTEGRATION_PROVIDER_LABELS,
  INTEGRATION_PROVIDERS,
  WEBHOOK_EVENTS,
} from '../lib/types'
import { cn, formatDate } from '../lib/utils'

const API_ORIGIN = API_BASE.replace(/\/api\/v1\/?$/, '')

function absolute(path: string | null): string | null {
  if (!path) return null
  return `${API_ORIGIN}${path}`
}

async function copy(
  text: string,
  toast: ReturnType<typeof useToast>,
  messages: { copied: string; error: string },
) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(messages.copied)
  } catch {
    toast.error(messages.error)
  }
}

function providerHint(provider: IntegrationProvider): { key: string; fallback: string } {
  switch (provider) {
    case 'github':
    case 'gitlab':
    case 'bitbucket':
      return {
        key: 'integrations.hintVcs',
        fallback: 'Branch/commit/PR links and optional auto-transitions via webhooks.',
      }
    case 'slack':
    case 'teams':
      return {
        key: 'integrations.hintChat',
        fallback: 'Posts TeamFlow events into a channel via an incoming webhook URL.',
      }
    case 'google_calendar':
      return {
        key: 'integrations.hintCalendar',
        fallback: 'Subscribe Google Calendar to a live ICS feed of due dates.',
      }
  }
}

export function IntegrationsPage() {
  const { org } = useOrg()
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const integrations = useIntegrations(org.slug)
  const events = useIntegrationEvents(org.slug)
  const [creating, setCreating] = useState(false)
  const [revealed, setRevealed] = useState<{ integration: IntegrationCreated } | null>(null)
  const [deleting, setDeleting] = useState<IntegrationRead | null>(null)
  const [form, setForm] = useState({
    provider: 'github' as IntegrationProvider,
    name: '',
    repository: '',
    webhook_url: '',
    opened: '',
    merged: '',
    push: '',
    events: ['task.created', 'task.completed'] as string[],
  })

  const copyMessages = {
    copied: t('integrations.copied', 'Copied to clipboard'),
    error: t('integrations.copyError', 'Could not copy'),
  }

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'integrations'] })
    void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'integration-events'] })
  }

  const create = useMutation({
    mutationFn: () => {
      const isVcs = ['github', 'gitlab', 'bitbucket'].includes(form.provider)
      const config: Record<string, unknown> = {}
      if (isVcs) {
        if (form.repository.trim()) config.repository = form.repository.trim()
        const auto: Record<string, string> = {}
        if (form.opened.trim()) auto.opened = form.opened.trim()
        if (form.merged.trim()) auto.merged = form.merged.trim()
        if (form.push.trim()) auto.push = form.push.trim()
        if (Object.keys(auto).length) config.auto_transition = auto
      }
      if (['slack', 'teams'].includes(form.provider)) {
        config.webhook_url = form.webhook_url.trim()
      }
      return integrationsApi.create(org.slug, {
        provider: form.provider,
        name: form.name.trim(),
        config,
        events: ['slack', 'teams'].includes(form.provider) ? form.events : [],
      })
    },
    onSuccess: (created) => {
      setCreating(false)
      invalidate()
      if (created.secret) {
        setRevealed({ integration: created })
      } else {
        toast.success(t('integrations.created', 'Integration created'))
      }
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('integrations.createError', 'Could not create integration'),
      ),
  })

  const update = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string
      data: Parameters<typeof integrationsApi.update>[2]
    }) => integrationsApi.update(org.slug, id, data),
    onSuccess: (updated, variables) => {
      invalidate()
      if (variables.data.rotate_secret && updated.secret) {
        setRevealed({ integration: updated })
      }
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('integrations.updateError', 'Could not update integration'),
      ),
  })

  const remove = useMutation({
    mutationFn: (integration: IntegrationRead) =>
      integrationsApi.remove(org.slug, integration.id),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success(t('integrations.deleted', 'Integration deleted'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('integrations.deleteError', 'Could not delete integration'),
      ),
  })

  const isChat = ['slack', 'teams'].includes(form.provider)
  const isVcs = ['github', 'gitlab', 'bitbucket'].includes(form.provider)
  const createValid =
    form.name.trim().length > 0 && (!isChat || form.webhook_url.trim().startsWith('http'))
  const hint = providerHint(form.provider)

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">
            {t('integrations.title', 'Integrations')}
          </h1>
          <p className="text-sm text-slate-500">
            {t(
              'integrations.subtitle',
              'Sync work with GitHub/GitLab/Bitbucket, Slack/Teams and Google Calendar.',
            )}
          </p>
        </div>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> {t('integrations.new', 'New integration')}
        </Button>
      </div>

      {integrations.isLoading && <PageSpinner />}
      {integrations.isError && (
        <ErrorState
          message={t('integrations.loadError', 'Could not load integrations.')}
          onRetry={() => void integrations.refetch()}
        />
      )}
      {integrations.data?.length === 0 && (
        <EmptyState
          icon={<Plug className="h-8 w-8" />}
          title={t('integrations.emptyTitle', 'No integrations yet')}
          description={t(
            'integrations.emptyDescription',
            'Connect a provider so work syncs where your team already is.',
          )}
        />
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {integrations.data?.map((integration) => {
          const webhookUrl = absolute(integration.webhook_path)
          return (
            <Card key={integration.id} className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    {INTEGRATION_PROVIDER_LABELS[integration.provider]}
                  </p>
                  <p className="text-xs text-slate-500">{integration.name}</p>
                </div>
                <span
                  className={cn(
                    'mt-1 h-2 w-2 rounded-full',
                    integration.is_active ? 'bg-emerald-500' : 'bg-slate-300',
                  )}
                />
              </div>
              <p className="text-xs text-slate-400">
                {integration.last_event_at
                  ? t('integrations.lastEvent', 'Last event {date}', {
                      date: formatDate(integration.last_event_at),
                    })
                  : t('integrations.noEvents', 'No events yet')}
              </p>
              {webhookUrl && (
                <button
                  className="flex w-full items-center gap-1 truncate rounded bg-slate-50 px-2 py-1 text-left text-[11px] text-slate-500 hover:bg-slate-100"
                  onClick={() => void copy(webhookUrl, toast, copyMessages)}
                  title={t('integrations.copyWebhookUrl', 'Copy webhook URL')}
                >
                  <Copy className="h-3 w-3 shrink-0" />
                  <span className="truncate">{webhookUrl}</span>
                </button>
              )}
              <div className="flex items-center justify-between gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => update.mutate({ id: integration.id, data: { is_active: !integration.is_active } })}
                >
                  {integration.is_active
                    ? t('integrations.disable', 'Disable')
                    : t('integrations.enable', 'Enable')}
                </Button>
                <div className="flex items-center gap-1">
                  {integration.has_secret && (
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t('integrations.rotateSecret', 'Rotate the secret / feed token')}
                      onClick={() =>
                        update.mutate({ id: integration.id, data: { rotate_secret: true } })
                      }
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    onClick={() => setDeleting(integration)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">
          {t('integrations.recentEvents', 'Recent integration events')}
        </h2>
        <div className="mt-2 space-y-1">
          {events.data?.length === 0 && (
            <p className="text-xs text-slate-400">
              {t('integrations.noEventsRecorded', 'No events recorded yet.')}
            </p>
          )}
          {events.data?.slice(0, 25).map((event) => (
            <div
              key={event.id}
              className="flex flex-wrap items-center gap-2 border-b border-slate-50 py-1 text-xs last:border-0"
            >
              <Badge
                className={
                  event.direction === 'inbound'
                    ? 'bg-sky-50 text-sky-700'
                    : 'bg-violet-50 text-violet-700'
                }
              >
                {t(`integrations.direction.${event.direction}`, event.direction)}
              </Badge>
              <span className="font-medium text-slate-700">{event.event_type}</span>
              <span className="text-slate-500">{event.status}</span>
              {event.detail && (
                <span className="min-w-0 flex-1 truncate text-slate-400" title={event.detail}>
                  {event.detail}
                </span>
              )}
              <span className="text-slate-400">{formatDate(event.created_at)}</span>
            </div>
          ))}
        </div>
      </div>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t('integrations.new', 'New integration')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button onClick={() => create.mutate()} disabled={!createValid} loading={create.isPending}>
              {t('common.create', 'Create')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label={t('integrations.provider', 'Provider')}>
            <Select
              value={form.provider}
              onChange={(event) =>
                setForm({ ...form, provider: event.target.value as IntegrationProvider })
              }
            >
              {INTEGRATION_PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {INTEGRATION_PROVIDER_LABELS[provider]}
                </option>
              ))}
            </Select>
          </Field>
          <p className="text-xs text-slate-500">{t(hint.key, hint.fallback)}</p>
          <Field
            label={t('common.name', 'Name')}
            hint={t('integrations.nameHint', 'A label for this connection')}
          >
            <Input
              value={form.name}
              maxLength={128}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder={
                isVcs
                  ? t('integrations.namePlaceholderVcs', 'teamflow/backend')
                  : isChat
                    ? t('integrations.namePlaceholderChat', 'engineering channel')
                    : t('integrations.namePlaceholderCalendar', 'My calendar')
              }
            />
          </Field>

          {isVcs && (
            <>
              <Field
                label={t('integrations.repository', 'Repository')}
                hint={t('integrations.repositoryHint', 'Optional, e.g. acme/backend')}
              >
                <Input
                  value={form.repository}
                  onChange={(event) => setForm({ ...form, repository: event.target.value })}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field
                  label={t('integrations.prOpened', 'PR opened →')}
                  hint={t('integrations.statusKeyHint', 'status key')}
                >
                  <Input
                    value={form.opened}
                    placeholder="in_review"
                    onChange={(event) => setForm({ ...form, opened: event.target.value })}
                  />
                </Field>
                <Field
                  label={t('integrations.prMerged', 'PR merged →')}
                  hint={t('integrations.statusKeyHint', 'status key')}
                >
                  <Input
                    value={form.merged}
                    placeholder="done"
                    onChange={(event) => setForm({ ...form, merged: event.target.value })}
                  />
                </Field>
                <Field
                  label={t('integrations.push', 'Push →')}
                  hint={t('integrations.statusKeyHint', 'status key')}
                >
                  <Input
                    value={form.push}
                    placeholder="in_progress"
                    onChange={(event) => setForm({ ...form, push: event.target.value })}
                  />
                </Field>
              </div>
            </>
          )}

          {isChat && (
            <>
              <Field label={t('integrations.incomingWebhookUrl', 'Incoming webhook URL')}>
                <Input
                  value={form.webhook_url}
                  onChange={(event) => setForm({ ...form, webhook_url: event.target.value })}
                  placeholder="https://hooks.slack.com/services/…"
                />
              </Field>
              <div className="space-y-1.5">
                <p className="text-sm font-medium text-slate-700">
                  {t('integrations.events', 'Events')}
                </p>
                {WEBHOOK_EVENTS.map((event) => (
                  <Checkbox
                    key={event}
                    label={event}
                    checked={form.events.includes(event)}
                    onChange={(input) =>
                      setForm({
                        ...form,
                        events: input.target.checked
                          ? [...form.events, event]
                          : form.events.filter((entry) => entry !== event),
                      })
                    }
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </Modal>

      <Modal
        open={Boolean(revealed)}
        onClose={() => setRevealed(null)}
        title={t('integrations.secretTitle', 'Integration secret')}
        size="sm"
        footer={
          <Button onClick={() => setRevealed(null)}>{t('integrations.done', 'Done')}</Button>
        }
      >
        {revealed && (
          <div className="space-y-3 text-sm text-slate-600">
            <p className="text-xs text-slate-500">
              {revealed.integration.provider === 'google_calendar'
                ? t(
                    'integrations.secretHintFeed',
                    'Shown once. Use it to verify webhooks or subscribe the ICS feed.',
                  )
                : t('integrations.secretHint', 'Shown once. Use it to verify webhooks.')}
            </p>
            <div className="flex items-center gap-2 rounded bg-slate-50 px-3 py-2 font-mono text-xs">
              <span className="min-w-0 flex-1 break-all">{revealed.integration.secret}</span>
              <button
                className="shrink-0 text-slate-400 hover:text-slate-700"
                onClick={() =>
                  void copy(revealed.integration.secret ?? '', toast, copyMessages)
                }
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
            {revealed.integration.feed_path && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-slate-500">
                  {t('integrations.calendarFeed', 'Calendar feed URL (webcal)')}
                </p>
                <div className="flex items-center gap-2 rounded bg-slate-50 px-3 py-2 text-xs">
                  <span className="min-w-0 flex-1 break-all">
                    {absolute(revealed.integration.feed_path)}?token={revealed.integration.secret}
                  </span>
                  <button
                    className="shrink-0 text-slate-400 hover:text-slate-700"
                    onClick={() =>
                      void copy(
                        `${absolute(revealed.integration.feed_path)}?token=${revealed.integration.secret}`,
                        toast,
                        copyMessages,
                      )
                    }
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={t('integrations.deleteTitle', 'Delete integration')}
        message={t(
          'integrations.deleteMessage',
          'Delete "{name}"? Events will stop syncing.',
          { name: deleting?.name ?? '' },
        )}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  )
}
