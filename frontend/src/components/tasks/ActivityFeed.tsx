import { Activity as ActivityIcon, Bot, MessageSquare, RefreshCw, Rocket, UserPlus } from 'lucide-react'

import { useProjectActivity, useTaskActivity } from '../../lib/hooks'
import type { ActivityRead } from '../../lib/types'
import { relativeTime } from '../../lib/utils'
import { Spinner } from '../ui'

type Scope = { type: 'task' | 'project'; id: string }

function iconFor(verb: string) {
  switch (verb) {
    case 'task_created':
      return <ActivityIcon className="h-3.5 w-3.5 text-sky-500" />
    case 'status_changed':
      return <RefreshCw className="h-3.5 w-3.5 text-amber-500" />
    case 'comment_created':
      return <MessageSquare className="h-3.5 w-3.5 text-slate-400" />
    case 'automation_ran':
      return <Bot className="h-3.5 w-3.5 text-violet-500" />
    case 'release_created':
    case 'release_published':
      return <Rocket className="h-3.5 w-3.5 text-emerald-500" />
    case 'task_assigned':
      return <UserPlus className="h-3.5 w-3.5 text-brand-500" />
    default:
      return <ActivityIcon className="h-3.5 w-3.5 text-slate-300" />
  }
}

export function ActivityFeed({ scope }: { scope: Scope }) {
  const taskQuery = useTaskActivity(scope.type === 'task' ? scope.id : undefined)
  const projectQuery = useProjectActivity(scope.type === 'project' ? scope.id : undefined)
  const query = scope.type === 'task' ? taskQuery : projectQuery
  const items: ActivityRead[] = query.data ?? []

  if (query.isLoading) {
    return (
      <div className="flex justify-center py-3">
        <Spinner className="h-4 w-4 text-slate-400" />
      </div>
    )
  }
  if (items.length === 0) {
    return <p className="py-2 text-xs text-slate-400">No activity yet.</p>
  }
  return (
    <ul className="mt-1 space-y-1.5">
      {items.map((entry) => (
        <li key={entry.id} className="flex items-start gap-2 text-xs">
          <span className="mt-0.5 shrink-0">{iconFor(entry.verb)}</span>
          <span className="min-w-0 flex-1 text-slate-600">
            <span className="font-medium text-slate-700">
              {entry.actor?.full_name || entry.actor?.email || 'TeamFlow'}
            </span>{' '}
            {entry.summary}
          </span>
          <span className="shrink-0 text-slate-400">{relativeTime(entry.created_at)}</span>
        </li>
      ))}
    </ul>
  )
}
