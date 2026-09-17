import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Copy, Plus, Trash2, Webhook } from 'lucide-react'
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
  Textarea,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, webhooksApi } from '../lib/api'
import { qk, useWebhookDeliveries, useWebhooks } from '../lib/hooks'
import { WEBHOOK_EVENTS, type WebhookCreated, type WebhookRead } from '../lib/types'
import { formatDateTime, relativeTime } from '../lib/utils'

export function WebhooksPage() {
  const { org } = useOrg()
  const webhooks = useWebhooks(org.slug)
  const queryClient = useQueryClient()
  const toast = useToast()

  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [description, setDescription] = useState('')
  const [events, setEvents] = useState<string[]>(['task.created', 'task.completed'])
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<WebhookCreated | null>(null)
  const [deleting, setDeleting] = useState<WebhookRead | null>(null)
  const [deliveriesFor, setDeliveriesFor] = useState<WebhookRead | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.webhooks(org.slug) })
  }

  const create = useMutation({
    mutationFn: () =>
      webhooksApi.create(org.slug, {
        url: url.trim(),
        events,
        description: description.trim() || null,
      }),
    onSuccess: (webhook) => {
      invalidate()
      setOpen(false)
      setUrl('')
      setDescription('')
      setError(null)
      setCreated(webhook)
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not create webhook'),
  })

  const toggleActive = useMutation({
    mutationFn: (webhook: WebhookRead) =>
      webhooksApi.update(org.slug, webhook.id, { is_active: !webhook.is_active }),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update webhook'),
  })

  const remove = useMutation({
    mutationFn: (webhookId: string) => webhooksApi.remove(org.slug, webhookId),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success('Webhook deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete webhook'),
  })

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Webhooks</h1>
          <p className="text-sm text-slate-500">
            Push TeamFlow events to external services, signed with HMAC-SHA256.
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> New webhook
        </Button>
      </div>

      {webhooks.isLoading && <PageSpinner />}
      {webhooks.isError && (
        <ErrorState message="Could not load webhooks." onRetry={() => void webhooks.refetch()} />
      )}

      {webhooks.data?.length === 0 && (
        <EmptyState
          icon={<Webhook className="h-8 w-8" />}
          title="No webhooks configured"
          description="Register an endpoint to receive task and comment events."
        />
      )}

      <div className="space-y-3">
        {webhooks.data?.map((webhook) => (
          <Card key={webhook.id} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-mono text-sm font-medium text-slate-800">{webhook.url}</p>
                {webhook.description && (
                  <p className="mt-0.5 text-xs text-slate-500">{webhook.description}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-1">
                  {webhook.events.map((event) => (
                    <Badge key={event} className="bg-slate-100 text-slate-600">
                      {event}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge
                  className={
                    webhook.is_active
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-100 text-slate-500'
                  }
                >
                  {webhook.is_active ? 'active' : 'paused'}
                </Badge>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => toggleActive.mutate(webhook)}
                  loading={toggleActive.isPending}
                >
                  {webhook.is_active ? 'Pause' : 'Resume'}
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setDeliveriesFor(webhook)}>
                  Deliveries
                </Button>
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  onClick={() => setDeleting(webhook)}
                  title="Delete webhook"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="New webhook"
        description="The signing secret is shown once, right after creation."
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              disabled={!url.trim() || events.length === 0}
            >
              Create webhook
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field label="Endpoint URL">
            <Input
              autoFocus
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com/hooks/teamflow"
            />
          </Field>
          <Field label="Description">
            <Textarea
              className="min-h-16"
              value={description}
              maxLength={255}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What consumes this webhook?"
            />
          </Field>
          <Field label="Events">
            <div className="space-y-1.5">
              {WEBHOOK_EVENTS.map((event) => (
                <Checkbox
                  key={event}
                  label={event}
                  checked={events.includes(event)}
                  onChange={(inputEvent) =>
                    setEvents((current) =>
                      inputEvent.target.checked
                        ? [...current, event]
                        : current.filter((entry) => entry !== event),
                    )
                  }
                />
              ))}
            </div>
          </Field>
        </div>
      </Modal>

      <Modal
        open={Boolean(created)}
        onClose={() => setCreated(null)}
        title="Webhook created"
        description="Copy the signing secret now — it cannot be retrieved again."
        footer={
          <Button onClick={() => setCreated(null)}>Done</Button>
        }
      >
        {created && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-slate-500">Signing secret</p>
            <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
              <code className="min-w-0 flex-1 break-all text-xs text-amber-900">{created.secret}</code>
              <button
                className="rounded p-1.5 text-amber-700 hover:bg-amber-100"
                onClick={() => {
                  void navigator.clipboard.writeText(created.secret)
                  toast.success('Secret copied')
                }}
                title="Copy secret"
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Verify deliveries with <code className="font-mono">X-TeamFlow-Signature</code> over{' '}
              <code className="font-mono">{'{timestamp}.{body}'}</code>.
            </p>
          </div>
        )}
      </Modal>

      <DeliveriesModal webhook={deliveriesFor} onClose={() => setDeliveriesFor(null)} />

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Delete webhook"
        message={`Delete the webhook for "${deleting?.url}"? Delivery history is removed too.`}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  )
}

function DeliveriesModal({
  webhook,
  onClose,
}: {
  webhook: WebhookRead | null
  onClose: () => void
}) {
  const { org } = useOrg()
  const deliveries = useWebhookDeliveries(org.slug, webhook?.id)

  return (
    <Modal
      open={Boolean(webhook)}
      onClose={onClose}
      title="Recent deliveries"
      description={webhook?.url}
      size="lg"
    >
      {deliveries.isLoading && <PageSpinner />}
      {deliveries.data?.length === 0 && (
        <p className="py-6 text-center text-sm text-slate-500">No deliveries yet.</p>
      )}
      {deliveries.data && deliveries.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-2 pr-4 font-medium">Event</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Attempts</th>
                <th className="py-2 pr-4 font-medium">Response</th>
                <th className="py-2 font-medium">When</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.data.map((delivery) => (
                <tr key={delivery.id} className="border-t border-slate-100">
                  <td className="py-2 pr-4 font-mono text-xs text-slate-700">{delivery.event}</td>
                  <td className="py-2 pr-4">
                    <Badge
                      className={
                        delivery.status === 'delivered'
                          ? 'bg-emerald-100 text-emerald-700'
                          : delivery.status === 'pending'
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-red-100 text-red-700'
                      }
                    >
                      {delivery.status}
                    </Badge>
                  </td>
                  <td className="py-2 pr-4 text-slate-600">{delivery.attempts}</td>
                  <td className="py-2 pr-4 text-slate-600">
                    {delivery.response_status ?? '—'}
                    {delivery.last_error && (
                      <span className="block text-xs text-red-500">{delivery.last_error}</span>
                    )}
                  </td>
                  <td className="py-2 text-slate-500" title={formatDateTime(delivery.created_at)}>
                    {relativeTime(delivery.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
