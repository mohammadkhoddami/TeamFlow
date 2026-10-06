import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Inbox } from 'lucide-react'

import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { qk, useBacklog, useSprints } from '../../lib/hooks'
import {
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  TYPE_BADGE,
  TYPE_LABELS,
  type TaskRead,
} from '../../lib/types'
import { Badge, EmptyState, PageSpinner, Select } from '../ui'

export function BacklogView({
  projectId,
  onOpen,
}: {
  projectId: string
  onOpen: (task: TaskRead) => void
}) {
  const backlog = useBacklog(projectId)
  const sprints = useSprints(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()

  const assign = useMutation({
    mutationFn: ({ taskId, sprintId }: { taskId: string; sprintId: string | null }) =>
      tasksApi.update(taskId, { sprint_id: sprintId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.backlog(projectId, 100) })
      void queryClient.invalidateQueries({ queryKey: qk.sprints(projectId) })
      void queryClient.invalidateQueries({ queryKey: ['orgs'] })
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not move the task'),
  })

  const items = backlog.data?.items ?? []
  const plannedSprints = (sprints.data ?? []).filter((sprint) => sprint.state !== 'completed')
  const totalPoints = items.reduce((sum, task) => sum + (task.estimate ?? 0), 0)

  if (backlog.isLoading) return <PageSpinner label="Loading backlog…" />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
        <span>
          {items.length} backlog task{items.length === 1 ? '' : 's'} (not in any sprint)
        </span>
        <span>{totalPoints ? `${totalPoints} pts` : 'No estimates yet'}</span>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon={<Inbox className="h-8 w-8" />}
          title="Backlog is empty"
          description="Every task is assigned to a sprint."
        />
      ) : (
        <div className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
          {items.map((task) => (
            <div
              key={task.id}
              className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2.5 hover:bg-slate-50"
              onClick={() => onOpen(task)}
            >
              {task.key && (
                <span className="w-16 shrink-0 font-mono text-[10px] text-slate-400">
                  {task.key}
                </span>
              )}
              <Badge className={TYPE_BADGE[task.type]}>{TYPE_LABELS[task.type]}</Badge>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
                {task.title}
              </span>
              {task.estimate != null && (
                <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                  {task.estimate} pts
                </span>
              )}
              <Badge className={PRIORITY_BADGE[task.priority]}>
                {PRIORITY_LABELS[task.priority]}
              </Badge>
              <div onClick={(event) => event.stopPropagation()}>
                <Select
                  className="w-auto"
                  value=""
                  onChange={(event) => {
                    if (event.target.value) {
                      assign.mutate({ taskId: task.id, sprintId: event.target.value })
                    }
                  }}
                >
                  <option value="">Add to sprint…</option>
                  {plannedSprints.map((sprint) => (
                    <option key={sprint.id} value={sprint.id}>
                      {sprint.name}
                      {sprint.state === 'active' ? ' (active)' : ''}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
