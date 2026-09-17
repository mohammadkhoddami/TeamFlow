import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { notificationsApi } from '../lib/api'
import { useNotifications, useUnreadCount } from '../lib/hooks'
import type { NotificationRead } from '../lib/types'
import { cn, relativeTime } from '../lib/utils'
import { Spinner } from './ui'

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const unread = useUnreadCount()
  const recent = useNotifications(false)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  const markRead = useMutation({
    mutationFn: notificationsApi.markRead,
    onSuccess: invalidate,
  })

  const markAllRead = useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: invalidate,
  })

  const count = unread.data?.unread ?? 0
  const items: NotificationRead[] = recent.data?.items.slice(0, 8) ?? []

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
        aria-label="Notifications"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
              <span className="text-sm font-semibold text-slate-800">Notifications</span>
              {count > 0 && (
                <button
                  className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
                  onClick={() => markAllRead.mutate()}
                  disabled={markAllRead.isPending}
                >
                  <CheckCheck className="h-3.5 w-3.5" /> Mark all read
                </button>
              )}
            </div>

            <div className="max-h-80 overflow-y-auto">
              {recent.isLoading && (
                <div className="flex justify-center py-6">
                  <Spinner className="h-4 w-4 text-slate-400" />
                </div>
              )}
              {!recent.isLoading && items.length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-slate-500">You're all caught up.</p>
              )}
              {items.map((notification) => (
                <button
                  key={notification.id}
                  className={cn(
                    'flex w-full flex-col gap-0.5 border-b border-slate-100 px-4 py-2.5 text-left last:border-0 hover:bg-slate-50',
                    !notification.read_at && 'bg-brand-50/50',
                  )}
                  onClick={() => {
                    if (!notification.read_at) markRead.mutate(notification.id)
                    setOpen(false)
                    if (slug) navigate(`/org/${slug}/notifications`)
                  }}
                >
                  <span className="text-sm font-medium text-slate-800">{notification.title}</span>
                  {notification.body && (
                    <span className="line-clamp-2 text-xs text-slate-500">{notification.body}</span>
                  )}
                  <span className="text-[11px] text-slate-400">
                    {relativeTime(notification.created_at)}
                  </span>
                </button>
              ))}
            </div>

            <button
              className="block w-full border-t border-slate-100 bg-slate-50 px-4 py-2.5 text-center text-xs font-medium text-brand-600 hover:bg-slate-100"
              onClick={() => {
                setOpen(false)
                if (slug) navigate(`/org/${slug}/notifications`)
              }}
            >
              View all notifications
            </button>
          </div>
        </>
      )}
    </div>
  )
}
