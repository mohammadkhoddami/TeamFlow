import { Plus } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { SwimlaneBy, TaskRead, WorkflowStatusRead } from '../../lib/types'
import { CATEGORY_BADGE } from '../../lib/types'
import { cn } from '../../lib/utils'
import { Badge } from '../ui'
import { TaskCard } from './TaskCard'

function laneValue(task: TaskRead, swimlaneBy: SwimlaneBy): string {
  if (swimlaneBy === 'assignee') {
    return task.assignee?.full_name || task.assignee?.email || 'Unassigned'
  }
  if (swimlaneBy === 'priority') {
    return task.priority
  }
  if (swimlaneBy === 'label') {
    return task.labels[0]?.name ?? 'No label'
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

  const columns = useMemo(
    () => [...statuses].sort((a, b) => a.position - b.position),
    [statuses],
  )

  const lanes = useMemo(() => {
    if (swimlaneBy === 'none') return [{ key: '', label: '', tasks }]
    const grouped = new Map<string, TaskRead[]>()
    for (const task of tasks) {
      const key = laneValue(task, swimlaneBy)
      grouped.set(key, [...(grouped.get(key) ?? []), task])
    }
    return [...grouped.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, laneTasks]) => ({ key, label: key, tasks: laneTasks }))
  }, [tasks, swimlaneBy])

  const renderColumn = (status: WorkflowStatusRead, laneTasks: TaskRead[]) => {
    const columnTasks = laneTasks.filter((task) => task.status === status.key)
    const overLimit =
      status.wip_limit != null && columnTasks.length > status.wip_limit
    return (
      <section
        key={status.key}
        className={cn(
          'flex min-h-40 flex-col rounded-xl border border-slate-200 bg-slate-100/60 p-2',
          overStatus === status.key && 'border-brand-400 bg-brand-50',
          overLimit && wipEnforced && 'border-red-300',
        )}
        onDragOver={(event) => {
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
              title={status.wip_limit != null ? `WIP limit ${status.wip_limit}` : undefined}
            >
              {columnTasks.length}
              {status.wip_limit != null ? `/${status.wip_limit}` : ''}
            </span>
          </div>
          {onAdd && (
            <button
              onClick={() => onAdd(status.key)}
              className="rounded-md p-1 text-slate-400 hover:bg-white hover:text-slate-700"
              title={`Add task to ${status.name}`}
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
            <p className="px-2 py-6 text-center text-xs text-slate-400">Drop tasks here</p>
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
                {lane.tasks.length} task{lane.tasks.length === 1 ? '' : 's'}
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
