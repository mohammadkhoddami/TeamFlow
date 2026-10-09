import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, CheckCheck, Layers, LayoutList, ListTree } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  PageSpinner,
} from '../components/ui'
import { notificationsApi } from '../lib/api'
import { useNotificationMutes, useNotifications, useProjects } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import type { NotificationRead } from '../lib/types'
import { cn, relativeTime } from '../lib/utils'

type GroupMode = 'project' | 'task' | 'none'

function groupNotifications(
  items: NotificationRead[],
  mode: GroupMode,
): { key: string; projectId: string | null; items: NotificationRead[] }[] {
  if (mode === 'none') {
    return [{ key: 'all', projectId: null, items }]
  }
  const groups = new Map<string, NotificationRead[]>()
  for (const item of items) {
    const key =
      mode === 'project' ? (item.project_id ?? 'none') : (item.task_id ?? 'none')
    const list = groups.get(key) ?? []
    list.push(item)
    groups.set(key, list)
  }
  return [...groups.entries()].map(([key, grouped]) => ({
    key,
    projectId: mode === 'project' && key !== 'none' ? key : (grouped[0]?.project_id ?? null),
    items: grouped,
  }))
}

export function NotificationsPage() {
  const { org } = useOrg()
  const { t } = useI18n()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [mode, setMode] = useState<GroupMode>('project')
  const notifications = useNotifications(unreadOnly)
  const mutes = useNotificationMutes()
  const projects = useProjects(org.slug)
  const queryClient = useQueryClient()

  const projectNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const project of projects.data ?? []) map.set(project.id, project.name)
    return map
  }, [projects.data])

  const mutedIds = useMemo(
    () => new Set((mutes.data ?? []).map((mute) => mute.project_id)),
    [mutes.data],
  )

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  const markRead = useMutation({ mutationFn: notificationsApi.markRead, onSuccess: invalidate })
  const markAll = useMutation({ mutationFn: notificationsApi.markAllRead, onSuccess: invalidate })

  const mute = useMutation({
    mutationFn: (projectId: string) => notificationsApi.addMute(projectId),
    onSuccess: invalidate,
  })
  const unmute = useMutation({
    mutationFn: (projectId: string) => notificationsApi.removeMute(projectId),
    onSuccess: invalidate,
  })
  const mutesBusy = mute.isPending || unmute.isPending

  const groups = useMemo(
    () => groupNotifications(notifications.data?.items ?? [], mode),
    [notifications.data, mode],
  )

  function labelFor(group: { key: string; items: NotificationRead[] }): string {
    if (mode === 'project') {
      return projectNames.get(group.key) ?? t('notifications.general', 'General')
    }
    if (mode === 'task') {
      const latest = group.items[0]
      return latest?.title ?? t('notifications.taskActivity', 'Task activity')
    }
    return t('notifications.allTitle', 'All notifications')
  }

  const modeButton = (value: GroupMode, icon: React.ReactNode, label: string) => (
    <button
      key={value}
      onClick={() => setMode(value)}
      className={cn(
        'flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-colors',
        mode === value
          ? 'bg-brand-50 text-brand-700'
          : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700',
      )}
    >
      {icon}
      {label}
    </button>
  )

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">
            {t('notifications.title', 'Notifications')}
          </h1>
          <p className="text-sm text-slate-500">
            {t('notifications.subtitle', 'Updates for you across all of your workspaces.')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5">
            {modeButton(
              'project',
              <Layers className="h-3.5 w-3.5" />,
              t('notifications.byProject', 'By project'),
            )}
            {modeButton(
              'task',
              <ListTree className="h-3.5 w-3.5" />,
              t('notifications.byTask', 'By task'),
            )}
            {modeButton(
              'none',
              <LayoutList className="h-3.5 w-3.5" />,
              t('notifications.flat', 'Flat'),
            )}
          </div>
          <Checkbox
            label={t('notifications.unreadOnly', 'Unread only')}
            checked={unreadOnly}
            onChange={(event) => setUnreadOnly(event.target.checked)}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => markAll.mutate()}
            loading={markAll.isPending}
          >
            <CheckCheck className="h-4 w-4" /> {t('notifications.markAllRead', 'Mark all read')}
          </Button>
        </div>
      </div>

      {(mutes.data?.length ?? 0) > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="font-medium">
            {t('notifications.mutedProjects', 'Muted projects:')}
          </span>
          {mutes.data?.map((entry) => (
            <button
              key={entry.id}
              onClick={() => unmute.mutate(entry.project_id)}
              disabled={mutesBusy}
              className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 font-medium text-slate-600 hover:border-slate-300"
              title={t('notifications.unmute', 'Unmute')}
            >
              <BellOff className="h-3 w-3" />
              {projectNames.get(entry.project_id) ?? entry.project_id.slice(0, 8)}
            </button>
          ))}
        </div>
      )}

      {notifications.isLoading && <PageSpinner />}
      {notifications.isError && (
        <ErrorState
          message={t('notifications.loadError', 'Could not load notifications.')}
          onRetry={() => void notifications.refetch()}
        />
      )}

      {notifications.data?.items.length === 0 && (
        <EmptyState
          icon={<Bell className="h-8 w-8" />}
          title={t('notifications.emptyTitle', 'Nothing here')}
          description={t('notifications.emptyBody', "You're all caught up.")}
        />
      )}

      <div className="space-y-5">
        {groups.map((group) => (
          <div key={group.key} className="space-y-2">
            {mode !== 'none' && (
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {labelFor(group)}
                  <Badge className="ml-2">{group.items.length}</Badge>
                </p>
                {group.projectId && (
                  <button
                    onClick={() =>
                      mutedIds.has(group.projectId as string)
                        ? unmute.mutate(group.projectId as string)
                        : mute.mutate(group.projectId as string)
                    }
                    disabled={mutesBusy}
                    className="flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-700"
                    title={
                      mutedIds.has(group.projectId)
                        ? t('notifications.unmuteProject', 'Unmute project')
                        : t('notifications.muteProject', 'Mute project')
                    }
                  >
                    {mutedIds.has(group.projectId) ? (
                      <>
                        <BellOff className="h-3.5 w-3.5" /> {t('notifications.muted', 'Muted')}
                      </>
                    ) : (
                      <>
                        <Bell className="h-3.5 w-3.5" /> {t('notifications.mute', 'Mute')}
                      </>
                    )}
                  </button>
                )}
              </div>
            )}
            {group.items.map((notification) => {
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
                      {t('notifications.meta', '{type} · {time}', {
                        type: notification.type,
                        time: relativeTime(notification.created_at),
                      })}
                      {notification.project_id &&
                        t('notifications.inProject', ' · {project}', {
                          project:
                            projectNames.get(notification.project_id) ??
                            t('notifications.projectFallback', 'project'),
                        })}
                      {notification.organization_id &&
                        !inThisOrg &&
                        t('notifications.otherWorkspace', ' · other workspace')}
                    </p>
                  </div>
                  {!notification.read_at && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => markRead.mutate(notification.id)}
                      loading={markRead.isPending}
                    >
                      {t('notifications.markRead', 'Mark read')}
                    </Button>
                  )}
                </Card>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
