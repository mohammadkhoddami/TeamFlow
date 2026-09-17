import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  PageSpinner,
} from '../components/ui'
import { notificationsApi } from '../lib/api'
import { useNotifications } from '../lib/hooks'
import { cn, relativeTime } from '../lib/utils'

export function NotificationsPage() {
  const { org } = useOrg()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const notifications = useNotifications(unreadOnly)
  const queryClient = useQueryClient()

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate })
  const markAll = useMutation({ mutationFn: notificationsApi.markAllRead, onSuccess: invalidate })

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Notifications</h1>
          <p className="text-sm text-slate-500">
            Updates for you across all of your workspaces.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Checkbox
            label="Unread only"
            checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => markAll.mutate()}
            loading={markAll.isPending}
          >
            <CheckCheck className="h-4 w-4" /> Mark all read
          </Button>
        </div>
      </div>

      {notifications.isLoading && <PageSpinner />}
      {notifications.isError && (
        <ErrorState
          message="Could not load notifications."
          onRetry={() => void notifications.refetch()}
        />
      )}

      {notifications.data?.items.length === 0 && (
        <EmptyState
          icon={<Bell className="h-8 w-8" />}
          title="Nothing here"
          description="You're all caught up."
        />
      )}

      <div className="space-y-2">
        {notifications.data?.items.map((notification) => {
          const inThisOrg = notification.organization_id === org.id
          return (
            <Card
              key={notification.id}
              className={cn(
                'flex items-start gap-3 p-4',
                !notification.read_at && 'border-brand-200 bg-brand-50/40',
              )}
            >
              <span
                className={cn(
                  'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                  notification.read_at ? 'bg-slate-200' : 'bg-brand-500',
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800">{notification.title}</p>
                {notification.body && (
                  <p className="mt-0.5 text-sm text-slate-600">{notification.body}</p>
                )}
                <p className="mt-1 text-xs text-slate-400">
                  {notification.type} · {relativeTime(notification.created_at)}
                  {notification.organization_id && (inThisOrg ? '' : ' · other workspace')}
                </p>
              </div>
              {!notification.read_at && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => markRead.mutate(notification.id)}
                  loading={markRead.isPending}
                >
                  Mark read
                </Button>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}
