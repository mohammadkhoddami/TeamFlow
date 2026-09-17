import { Plus } from 'lucide-react'
import { useState } from 'react'

import { STATUS_BADGE, STATUS_LABELS, TASK_STATUSES, type TaskRead, type TaskStatus } from '../../lib/types'
import { cn } from '../../lib/utils'
import { Badge } from '../ui'
import { TaskCard } from './TaskCard'

export function TaskBoard({
  tasks,
  onMove,
  onOpen,
  onAdd,
}: {
  tasks: TaskRead[]
  onMove: (taskId: string, status: TaskStatus) => void
  onOpen: (task: TaskRead) => void
  onAdd?: (status: TaskStatus) => void
}) {
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [overStatus, setOverStatus] = useState<TaskStatus | null>(null)

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      {TASK_STATUSES.map((status) => {
        const columnTasks = tasks.filter((task) => task.status === status)
        return (
          <section
            key={status}
            className={cn(
              'flex min-h-40 flex-col rounded-xl border border-slate-200 bg-slate-100/60 p-2',
              overStatus === status && 'border-brand-400 bg-brand-50',
            )}
            onDragOver={(event) => {
              event.preventDefault()
              setOverStatus(status)
            }}
            onDragLeave={() => setOverStatus((current) => (current === status ? null : current))}
            onDrop={(event) => {
              event.preventDefault()
              setOverStatus(null)
              const taskId = event.dataTransfer.getData('text/task-id') || draggingId
              const task = tasks.find((entry) => entry.id === taskId)
              if (task && task.status !== status) onMove(task.id, status)
              setDraggingId(null)
            }}
          >
            <header className="flex items-center justify-between px-2 py-1.5">
              <div className="flex items-center gap-2">
                <Badge className={STATUS_BADGE[status]}>{STATUS_LABELS[status]}</Badge>
                <span className="text-xs font-medium text-slate-500">{columnTasks.length}</span>
              </div>
              {onAdd && (
                <button
                  onClick={() => onAdd(status)}
                  className="rounded-md p-1 text-slate-400 hover:bg-white hover:text-slate-700"
                  title={`Add task to ${STATUS_LABELS[status]}`}
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
                  Drop tasks here
                </p>
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}
