import { CalendarDays } from 'lucide-react'

import { Avatar, Badge } from '../ui'
import type { TaskRead } from '../../lib/types'
import { PRIORITY_BADGE, PRIORITY_LABELS } from '../../lib/types'
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
  const overdue = isOverdue(task.due_date, task.status)

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      className="cursor-pointer rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing"
    >
      <div className="flex items-center justify-between gap-2">
        <Badge className={PRIORITY_BADGE[task.priority]}>{PRIORITY_LABELS[task.priority]}</Badge>
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

      <p className="mt-2 line-clamp-2 text-sm font-medium text-slate-800">{task.title}</p>

      <div className="mt-3 flex items-center justify-between gap-2">
        {task.assignee ? (
          <Avatar
            name={task.assignee.full_name || task.assignee.email}
            email={task.assignee.email}
            size="sm"
          />
        ) : (
          <span className="text-[11px] text-slate-400">Unassigned</span>
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
