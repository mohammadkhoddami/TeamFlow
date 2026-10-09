import { Plus } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { SwimlaneBy, TaskRead, WorkflowStatusRead } from '../../lib/types'
import { CATEGORY_BADGE, PRIORITY_LABELS } from '../../lib/types'
import { useI18n } from '../../lib/i18n'
import { cn } from '../../lib/utils'
import { Badge } from '../ui'
import { TaskCard } from './TaskCard'

type Translate = (key: string, fallback?: string, vars?: Record<string, string | number>) => string

function laneKey(task: TaskRead, swimlaneBy: SwimlaneBy): string {
  if (swimlaneBy === 'assignee') {
    return task.assignee?.id ?? '__unassigned__'
  }
  if (swimlaneBy === 'priority') {
    return task.priority
  }
  if (swimlaneBy === 'label') {
    return task.labels[0]?.id ?? '__no_label__'
  }
  return ''
}

function laneLabel(task: TaskRead, swimlaneBy: SwimlaneBy, t: Translate): string {
  if (swimlaneBy === 'assignee') {
    return task.assignee?.full_name || task.assignee?.email || t('common.unassigned', 'Unassigned')
  }
  if (swimlaneBy === 'priority') {
    return t(`priority.${task.priority}`, PRIORITY_LABELS[task.priority])
  }
  if (swimlaneBy === 'label') {
    return task.labels[0]?.name ?? t('tasks.laneNoLabel', 'No label')
  }
  return ''
}

export function TaskBoard({
  tasks,
  statuses,
  swimlaneBy = 'none',
  wipEnforced = false,
  onMove,
  onOpen,
  onAdd,
}: {
  tasks: TaskRead[]
  statuses: WorkflowStatusRead[]
  swimlaneBy?: SwimlaneBy
  wipEnforced?: boolean
  onMove: (taskId: string, status: string) => void
  onOpen: (task: TaskRead) => void
  onAdd?: (status: string) => void
}) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [overStatus, setOverStatus] = useState<string | null>(null)
  const { t } = useI18n()

  const columns = useMemo(
    () => [...statuses].sort((a, b) => a.position - b.position),
    [statuses],
  )

  const statusMap = useMemo(
    () => new Map(columns.map((status) => [status.key, status])),
    [columns],
  )
  // While dragging, only the current status and its allowed next statuses are
  // drop targets - the project workflow is enforced in the UI, not just by the
  // server response after a drop.
  const draggingTask = draggingId
    ? tasks.find((task) => task.id === draggingId)
    : undefined
  const allowedTargets = useMemo(() => {
    if (!draggingTask) return null
    const current = statusMap.get(draggingTask.status)
    if (!current) return null
    return new Set(current.transitions)
  }, [draggingTask, statusMap])

  const lanes = useMemo(() => {
    if (swimlaneBy === 'none') return [{ key: '', label: '', tasks }]
    const grouped = new Map<string, TaskRead[]>()
    for (const task of tasks) {
      const key = laneKey(task, swimlaneBy)
      grouped.set(key, [...(grouped.get(key) ?? []), task])
    }
    return [...grouped.entries()]
      .map(([key, laneTasks]) => ({
        key,
        label: laneLabel(laneTasks[0], swimlaneBy, t),
        tasks: laneTasks,
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [tasks, swimlaneBy, t])

  const renderColumn = (status: WorkflowStatusRead, laneTasks: TaskRead[]) => {
    const columnTasks = laneTasks.filter((task) => task.status === status.key)
    const overLimit =
      status.wip_limit != null && columnTasks.length > status.wip_limit
    const canDrop =
      !draggingTask ||
      allowedTargets === null ||
      draggingTask.status === status.key ||
      allowedTargets.has(status.key)
    return (
      <section
        key={status.key}
        className={cn(
          'flex min-h-40 flex-col rounded-xl border border-slate-200 bg-slate-100/60 p-2',
          overStatus === status.key && 'border-brand-400 bg-brand-50',
          overLimit && wipEnforced && 'border-red-300',
          !canDrop && 'opacity-50',
        )}
        title={
          !canDrop
            ? t('tasks.transitionNotAllowed', 'Not allowed from the current status')
            : undefined
        }
        onDragOver={(event) => {
          if (!canDrop) return
          event.preventDefault()
          setOverStatus(status.key)
        }}
        onDragLeave={() => setOverStatus((current) => (current === status.key ? null : current))}
        onDrop={(event) => {
          event.preventDefault()
          setOverStatus(null)
          const taskId = event.dataTransfer.getData('text/task-id') || draggingId
          const task = tasks.find((entry) => entry.id === taskId)
          if (task && task.status !== status.key) onMove(task.id, status.key)
          setDraggingId(null)
        }}
      >
        <header className="flex items-center justify-between px-2 py-1.5">
          <div className="flex items-center gap-2">
            <Badge className={CATEGORY_BADGE[status.category]}>{status.name}</Badge>
            <span
              className={cn(
                'text-xs font-medium',
                overLimit && wipEnforced ? 'text-red-600' : 'text-slate-500',
              )}
              title={
                status.wip_limit != null
                  ? t('tasks.wipLimit', 'WIP limit {limit}', { limit: status.wip_limit })
                  : undefined
              }
            >
              {columnTasks.length}
              {status.wip_limit != null ? `/${status.wip_limit}` : ''}
            </span>
          </div>
          {onAdd && (
            <button
              onClick={() => onAdd(status.key)}
              className="rounded-md p-1 text-slate-400 hover:bg-white hover:text-slate-700"
              title={t('tasks.addTaskTo', 'Add task to {status}', { status: status.name })}
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          )}
        </header>

        <div className="flex flex-1 flex-col gap-2 p-1">
          {columnTasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onOpen={() => onOpen(task)}
              onDragStart={(event) => {
                event.dataTransfer.setData('text/task-id', task.id)
                event.dataTransfer.effectAllowed = 'move'
                setDraggingId(task.id)
              }}
              onDragEnd={() => setDraggingId(null)}
            />
          ))}
          {columnTasks.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-slate-400">
              {t('tasks.dropTasksHere', 'Drop tasks here')}
            </p>
          )}
        </div>
      </section>
    )
  }

  return (
    <div className="space-y-6">
      {lanes.map((lane) => (
        <div key={lane.key || 'all'}>
          {lane.label && (
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {lane.label}
              <span className="ml-2 font-normal normal-case text-slate-400">
                {lane.tasks.length === 1
                  ? t('tasks.laneTaskCountOne', '{count} task', { count: lane.tasks.length })
                  : t('tasks.laneTaskCount', '{count} tasks', { count: lane.tasks.length })}
              </span>
            </p>
          )}
          <div
            className={cn(
              'grid grid-cols-1 gap-4 md:grid-cols-2',
              columns.length >= 4 ? 'xl:grid-cols-4' : 'xl:grid-cols-3',
            )}
          >
            {columns.map((status) => renderColumn(status, lane.tasks))}
          </div>
        </div>
      ))}
    </div>
  )
}
