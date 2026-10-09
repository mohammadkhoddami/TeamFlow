import { CalendarDays, CheckSquare, CornerDownRight, GitBranch, ShieldAlert } from 'lucide-react'

import { Avatar, Badge } from '../ui'
import type { TaskRead } from '../../lib/types'
import {
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  TYPE_BADGE,
  TYPE_LABELS,
} from '../../lib/types'
import { useI18n } from '../../lib/i18n'
import { cn, formatDate, isOverdue } from '../../lib/utils'

export function TaskCard({
  task,
  onOpen,
  onDragStart,
  onDragEnd,
}: {
  task: TaskRead
  onOpen: () => void
  onDragStart: (event: React.DragEvent) => void
  onDragEnd: () => void
}) {
  const { t } = useI18n()
  const overdue = isOverdue(task.due_date, task.status)
  const isContainer = task.child_count > 0
  const progress = isContainer
    ? Math.round((task.done_child_count / task.child_count) * 100)
    : 0

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      className="cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Badge className={TYPE_BADGE[task.type]}>{t(`type.${task.type}`, TYPE_LABELS[task.type])}</Badge>
          <Badge className={PRIORITY_BADGE[task.priority]}>
            {t(`priority.${task.priority}`, PRIORITY_LABELS[task.priority])}
          </Badge>
          {task.key && (
            <span className="font-mono text-[10px] text-slate-400">{task.key}</span>
          )}
          {task.estimate != null && (
            <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
              {task.estimate}
            </span>
          )}
        </div>
        {task.labels.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1">
            {task.labels.slice(0, 3).map((label) => (
              <span
                key={label.id}
                className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: label.color ?? '#94a3b8' }}
                />
                {label.name}
              </span>
            ))}
            {task.labels.length > 3 && (
              <span className="text-[10px] text-slate-400">+{task.labels.length - 3}</span>
            )}
          </div>
        )}
      </div>

      {task.parent && (
        <p className="mt-2 flex items-center gap-1 truncate text-[10px] text-slate-400">
          <CornerDownRight className="h-3 w-3 shrink-0" />
          <span className="truncate">
            {t('tasks.parentRef', '{type} · {title}', {
              type: t(`type.${task.parent.type}`, TYPE_LABELS[task.parent.type]),
              title: task.parent.title,
            })}
          </span>
        </p>
      )}

      <p className="mt-1.5 line-clamp-2 text-sm font-medium text-slate-800">{task.title}</p>

      {isContainer && (
        <div className="mt-2 space-y-1">
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1">
              <GitBranch className="h-3 w-3" />
              {t('tasks.doneCount', '{done}/{total} done', {
                done: task.done_child_count,
                total: task.child_count,
              })}
            </span>
            <span>{progress}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-slate-100">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                progress === 100 ? 'bg-emerald-500' : 'bg-brand-500',
              )}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
        {task.is_blocked && (
          <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-1.5 py-0.5 font-medium text-red-700">
            <ShieldAlert className="h-3 w-3" /> {t('tasks.blocked', 'blocked')}
          </span>
        )}
        {task.checklist_total > 0 && (
          <span className="inline-flex items-center gap-1">
            <CheckSquare className="h-3 w-3" />
            {task.checklist_done}/{task.checklist_total}
          </span>
        )}
        {task.assignees.length > 1 && (
          <span>
            {task.assignees.length - 1 === 1
              ? t('tasks.assigneesMoreOne', '+{count} assignee', {
                  count: task.assignees.length - 1,
                })
              : t('tasks.assigneesMore', '+{count} assignees', {
                  count: task.assignees.length - 1,
                })}
          </span>
        )}
        {task.logged_minutes > 0 && (
          <span>
            {task.logged_minutes % 60
              ? t('tasks.loggedTime', '{hours}h {minutes}m logged', {
                  hours: Math.floor(task.logged_minutes / 60),
                  minutes: task.logged_minutes % 60,
                })
              : t('tasks.loggedTimeHours', '{hours}h logged', {
                  hours: Math.floor(task.logged_minutes / 60),
                })}
          </span>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        {task.assignee ? (
          <Avatar
            name={task.assignee.full_name || task.assignee.email}
            email={task.assignee.email}
            size="sm"
          />
        ) : (
          <span className="text-[11px] text-slate-400">{t('common.unassigned', 'Unassigned')}</span>
        )}
        {task.due_date && (
          <span
            className={cn(
              'inline-flex items-center gap-1 text-[11px]',
              overdue ? 'font-medium text-red-600' : 'text-slate-500',
            )}
          >
            <CalendarDays className="h-3 w-3" />
            {formatDate(task.due_date)}
          </span>
        )}
      </div>
    </div>
  )
}
