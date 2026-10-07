import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BellRing, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, notificationsApi } from '../../lib/api'
import { qk, usePushSubscriptions } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import { subscribeBrowserToPush } from '../../lib/push'
import { formatDate } from '../../lib/utils'
import { Badge, Button, Card, CardHeader, ErrorState } from '../ui'

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined

export function PushSection() {
  const toast = useToast()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const subscriptions = usePushSubscriptions()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: qk.pushSubscriptions })

  const remove = useMutation({
    mutationFn: (subscriptionId: string) =>
      notificationsApi.unsubscribePush(subscriptionId),
    onSuccess: () => {
      invalidate()
      toast.success('Subscription removed')
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not remove subscription'),
  })

  async function enable() {
    setBusy(true)
    setError(null)
    try {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        throw new Error('Push notifications are not supported by this browser.')
      }
      if (!VAPID_PUBLIC_KEY) {
        throw new Error('VITE_VAPID_PUBLIC_KEY is not configured.')
      }
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        throw new Error('Notification permission was not granted.')
      }
      const subscription = await subscribeBrowserToPush(VAPID_PUBLIC_KEY)
      await notificationsApi.subscribePush({
        endpoint: subscription.endpoint,
        keys: subscription.keys,
        user_agent: navigator.userAgent,
      })
      invalidate()
      toast.success('Push notifications enabled on this device')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not enable push notifications')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title={t('settings.push', 'Push notifications')}
        description="Browser alerts for assignments, mentions and due dates."
      />
      <div className="space-y-4 p-5">
        {!VAPID_PUBLIC_KEY && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            Push is disabled: set <code>VITE_VAPID_PUBLIC_KEY</code> to your server's public
            VAPID key and rebuild.
          </p>
        )}
        {error && <ErrorState message={error} />}
        <div className="flex justify-end">
          <Button onClick={() => void enable()} loading={busy} disabled={!VAPID_PUBLIC_KEY}>
            <BellRing className="h-3.5 w-3.5" /> Enable on this device
          </Button>
        </div>
        {(subscriptions.data?.length ?? 0) === 0 && (
          <p className="text-sm text-slate-400">No push subscriptions for your account.</p>
        )}
        {subscriptions.data?.map((subscription) => {
          let host = subscription.endpoint
          try {
            host = new URL(subscription.endpoint).host
          } catch {
            host = subscription.endpoint.slice(0, 48)
          }
          return (
            <div
              key={subscription.id}
              className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">{host}</p>
                <p className="text-xs text-slate-500">
                  Added {formatDate(subscription.created_at)}
                  {subscription.user_agent ? ` · ${subscription.user_agent.slice(0, 60)}` : ''}
                </p>
              </div>
              <Badge className="bg-emerald-100 text-emerald-700">active</Badge>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                title="Remove subscription"
                onClick={() => remove.mutate(subscription.id)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
